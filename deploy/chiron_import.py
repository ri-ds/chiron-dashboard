#!/usr/bin/env python
"""Create a Chiron project and load CSV data into it.

Runs INSIDE the chiron-api container, driven by the dashboard:

    python manage.py shell < chiron_import.py            (args via IMPORT_ARGS)

It does not invent an import mechanism. Chiron already has one:

    Dataset (project) -> Collection (table) -> Source -> Processor

and ships `SourceCsv`, which reads a header-row CSV and matches each record to a
subject by a named column. So importing is: point Sources at the files, then run
Chiron's own `chiron_run_etl`, which does a full truncate-and-reload. That last
detail is why re-importing is safe — it replaces rather than accumulating.

Two modes:

  preview   Read the files, check every Source's required subject-ID column is
            actually present, count rows, and report what WOULD happen. Writes
            nothing, touches no database.

  import    Repoint the target dataset's CSV Sources at the chosen folder, then
            run the ETL. With --new-project, first clone an existing dataset's
            structure (collections, sources, concepts) under a new unique_id, so
            the new project inherits a known-good data dictionary instead of one
            assembled from guesses.

Results are printed as a single JSON line prefixed with RESULT: so the caller
can parse it without depending on Django's other chatter.
"""

import csv
import json
import os
import sys
import traceback

from django.core.management import call_command
from django.db import transaction

from chiron.models import Collection, Concept, Dataset, Source, SourceProcessorArg

# Where the dashboard mounts the data inside this container. Chiron's SourceCsv
# prepends CHIRON_SOURCE_DATA_DIRECTORY (empty here) so paths are relative to the
# project directory, which is why this is a relative path.
IMPORT_DIR = "source_data_import"


def emit(payload):
    print("RESULT:" + json.dumps(payload))


def csv_columns(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return next(csv.reader(f), [])


def count_rows(path):
    with open(path, "rb") as f:
        return max(sum(1 for _ in f) - 1, 0)


def csv_sources(dataset):
    return [s for s in Source.objects.filter(collection__dataset=dataset)
            if s.processor.name == "SourceCsv"]


def source_args(source):
    return {a.name: a.value for a in SourceProcessorArg.objects.filter(source=source)}


def preview(dataset_id, folder):
    """Everything that could go wrong, found before anything is written."""
    ds = Dataset.objects.filter(unique_id=dataset_id).first()
    if ds is None:
        return {"ok": False, "error": f"No dataset '{dataset_id}'."}

    abs_dir = os.path.join(os.getcwd(), folder)
    if not os.path.isdir(abs_dir):
        return {"ok": False, "error": f"No data folder at {abs_dir}."}

    available = sorted(f for f in os.listdir(abs_dir) if f.endswith(".csv"))
    plan, problems = [], []

    for src in csv_sources(ds):
        args = source_args(src)
        filename = os.path.basename(args.get("filepath", ""))
        subject_field = args.get("subject_matching_source_id_field")
        collection_field = args.get("collection_id_field")
        new_path = os.path.join(abs_dir, filename)

        entry = {"source": src.name, "collection": src.collection.name,
                 "file": filename, "concepts": src.concept_set.count(),
                 "subject_id_field": subject_field}

        if not os.path.isfile(new_path):
            entry["status"] = "skip"
            entry["detail"] = f"{filename} not in this folder; source left untouched"
            plan.append(entry)
            continue

        cols = csv_columns(new_path)
        missing = [c for c in (subject_field, collection_field)
                   if c and c not in cols]
        if missing:
            # Without the subject-ID column SourceCsv cannot match records to
            # subjects, so this would fail mid-ETL rather than up front.
            entry["status"] = "error"
            entry["detail"] = f"missing column(s): {', '.join(missing)}"
            problems.append(entry["detail"])
        else:
            entry["status"] = "ok"
            entry["rows"] = count_rows(new_path)
            mapped = [c.permanent_id for c in src.concept_set.all()]
            entry["detail"] = f"{entry['rows']:,} rows · {len(mapped)} mapped concepts"
        plan.append(entry)

    loadable = [p for p in plan if p["status"] == "ok"]
    return {
        "ok": not problems,
        "dataset": dataset_id,
        "folder": folder,
        "files_in_folder": available,
        "plan": plan,
        "total_rows": sum(p.get("rows", 0) for p in loadable),
        "loadable_sources": len(loadable),
        "problems": problems,
    }


def clone_dataset(template, new_id, display_name):
    """Copy a dataset's structure so a new project starts from a working one.

    Concepts carry the data dictionary. Rebuilding one from scratch means
    guessing at types and processors; cloning inherits definitions already known
    to load, and only the file paths differ.
    """
    if Dataset.objects.filter(unique_id=new_id).exists():
        raise ValueError(f"A dataset '{new_id}' already exists.")

    new_ds = Dataset.objects.create(
        unique_id=new_id,
        display_name=display_name or new_id,
        database_name=new_id.replace("-", "_"),
        description=f"Imported from {IMPORT_DIR} (synthetic data).",
        auto_access_level=getattr(template, "auto_access_level", "phi"),
        autocreate_chiron_user=True,
        list_visible=True,
    )

    col_map = {}
    for col in Collection.objects.filter(dataset=template):
        new_col = Collection.objects.create(
            dataset=new_ds, permanent_id=col.permanent_id, name=col.name,
            name_plural=col.name_plural,
            many_to_many_with_subject=col.many_to_many_with_subject,
            collection_id_is_integer=col.collection_id_is_integer,
        )
        col_map[col.id] = new_col
        if template.root_collection_id == col.id:
            new_ds.root_collection = new_col
            new_ds.save()

    for src in Source.objects.filter(collection__dataset=template):
        new_src = Source.objects.create(
            name=src.name, collection=col_map[src.collection_id],
            processor=src.processor, execution_order=src.execution_order,
            exclude_from_etl=src.exclude_from_etl,
        )
        for arg in SourceProcessorArg.objects.filter(source=src):
            SourceProcessorArg.objects.create(source=new_src, name=arg.name,
                                              value=arg.value)
        for concept in src.concept_set.all():
            # Concept.permanent_id is unique across the whole install, not per
            # dataset, so a clone has to namespace them or it collides with the
            # template's. The new project's concepts are therefore prefixed.
            original = concept.permanent_id
            concept.pk = None
            concept.id = None
            concept.permanent_id = f"{new_id}__{original}"[:120]
            concept.collection = col_map[src.collection_id]
            concept.source = new_src
            concept.save()

    return new_ds


def do_import(dataset_id, folder, new_project=None, display_name=None):
    ds = Dataset.objects.filter(unique_id=dataset_id).first()
    if ds is None:
        return {"ok": False, "error": f"No dataset '{dataset_id}'."}

    target = ds
    created = False
    if new_project:
        with transaction.atomic():
            target = clone_dataset(ds, new_project, display_name)
        created = True

    abs_dir = os.path.join(os.getcwd(), folder)
    repointed = []
    with transaction.atomic():
        for src in csv_sources(target):
            arg = SourceProcessorArg.objects.filter(source=src, name="filepath").first()
            if not arg:
                continue
            filename = os.path.basename(arg.value)
            if not os.path.isfile(os.path.join(abs_dir, filename)):
                continue  # leave sources whose file this folder does not provide
            arg.value = f"{folder}/{filename}"
            arg.save()
            repointed.append(f"{src.name} -> {arg.value}")

    if not repointed:
        return {"ok": False, "created": created, "dataset": target.unique_id,
                "error": "No source matched a file in that folder; nothing to load."}

    # Chiron's own ETL. Full truncate and reload, so this is repeatable.
    call_command("chiron_run_etl", target.unique_id, force=True)

    return {"ok": True, "created": created, "dataset": target.unique_id,
            "repointed": repointed}


def main():
    try:
        args = json.loads(os.environ.get("IMPORT_ARGS", "{}"))
        action = args.get("action", "preview")
        folder = args.get("folder", IMPORT_DIR)
        if action == "preview":
            emit(preview(args.get("dataset", "dataset1_stored"), folder))
        elif action == "import":
            emit(do_import(args.get("dataset", "dataset1_stored"), folder,
                           args.get("new_project"), args.get("display_name")))
        elif action == "datasets":
            emit({"ok": True, "datasets": [
                {"unique_id": d.unique_id, "display_name": d.display_name,
                 "csv_sources": len(csv_sources(d))}
                for d in Dataset.objects.all()]})
        else:
            emit({"ok": False, "error": f"unknown action {action}"})
    except Exception as exc:
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}",
              "trace": traceback.format_exc()[-1200:]})


main()
