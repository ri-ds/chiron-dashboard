"""Build a complete Chiron project from a folder of Synthea CSVs, then load it.

The earlier import only moved patients.csv, because that was the one file this
Chiron already had a Source for. Everything else sat unread. This creates the
missing structure so all six files load:

    Dataset
      Collections   subject (root), encounter, observation, condition,
                    medication, procedure
      Sources       one SourceCsv per file, matched to subjects by PATIENT
      Concepts      one per column, with the handler its type needs

Then it runs Chiron's own chiron_run_etl. Nothing here reimplements loading; it
only supplies the data dictionary Chiron needs in order to do it.

Safe by construction: it refuses to touch an existing project. A build either
creates a brand-new dataset or fails, so no fixture can be overwritten.

Args arrive as JSON in BUILD_ARGS. Result is one RESULT: line of JSON.
"""

import csv
import json
import os
import traceback

from django.core.management import call_command
from django.db import transaction

from chiron.models import (Category, Collection, Concept, ConceptHandler,
                           ConceptHandlerArg, Dataset, Processor, Source,
                           SourceProcessorArg)

# type -> ConceptHandler name. Chiron casts on load and silently nulls anything
# that fails its cast, so choosing the right handler is what decides whether a
# column arrives as data or as a hole.
H = {"date": "DateHandler", "cat": "CategoryHandler", "text": "TextHandler",
     "float": "FloatHandler", "int": "IntegerHandler"}

# One entry per Synthea file: which collection it becomes, how rows map to a
# subject, and the columns worth loading with their types.
LAYOUT = [
    {"file": "patients.csv", "collection": "subject", "root": True,
     "subject_field": "Id", "collection_id": "Id", "category": "demographics",
     "columns": [("BIRTHDATE", "date"), ("DEATHDATE", "date"),
                 ("FIRST", "text"), ("LAST", "text"), ("GENDER", "cat"),
                 ("RACE", "cat"), ("ETHNICITY", "cat"),
                 (["MARRIED", "MARITAL"], "cat"),
                 ("CITY", "cat"), ("STATE", "cat"), ("COUNTY", "cat"),
                 ("ZIP", "text"), ("HEALTHCARE_EXPENSES", "float"),
                 ("HEALTHCARE_COVERAGE", "float"), ("INCOME", "int"),
                 ("STUDY_GROUP_A", "cat"), ("STUDY_GROUP_B", "cat"),
                 ("STUDY_GROUP_C", "cat")]},
    {"file": "encounters.csv", "collection": "encounter", "root": False,
     "subject_field": "PATIENT", "collection_id": "Id", "category": "encounters",
     "columns": [("START", "date"), ("STOP", "date"), ("ENCOUNTERCLASS", "cat"),
                 ("CODE", "cat"), ("DESCRIPTION", "cat"),
                 ("BASE_ENCOUNTER_COST", "float"), ("TOTAL_CLAIM_COST", "float"),
                 ("PAYER_COVERAGE", "float"), ("ORGANIZATION", "cat"),
                 ("PROVIDER", "text"), ("PAYER", "cat")]},
    {"file": "observations.csv", "collection": "observation", "root": False,
     "subject_field": "PATIENT", "collection_id": None, "category": "observations",
     "columns": [("DATE", "date"), ("CATEGORY", "cat"), ("CODE", "cat"),
                 ("DESCRIPTION", "cat"), ("VALUE", "float"), ("UNITS", "cat")]},
    {"file": "conditions.csv", "collection": "condition", "root": False,
     "subject_field": "PATIENT", "collection_id": None, "category": "conditions",
     "columns": [("START", "date"), ("STOP", "date"), ("CODE", "cat"),
                 ("DESCRIPTION", "cat")]},
    {"file": "medications.csv", "collection": "medication", "root": False,
     "subject_field": "PATIENT", "collection_id": None, "category": "medications",
     "columns": [("START", "date"), ("STOP", "date"), ("CODE", "cat"),
                 ("DESCRIPTION", "cat"), ("BASE_COST", "float"),
                 ("DISPENSES", "int"), ("TOTALCOST", "float"),
                 ("REASONDESCRIPTION", "cat")]},
    {"file": "procedures.csv", "collection": "procedure", "root": False,
     "subject_field": "PATIENT", "collection_id": None, "category": "procedures",
     "columns": [("START", "date"), ("CODE", "cat"), ("DESCRIPTION", "cat"),
                 ("BASE_COST", "float")]},
    # Present in a real Synthea export, absent from ours. Missing files are
    # skipped, so listing them costs nothing and covers real data when it arrives.
    {"file": "allergies.csv", "collection": "allergy", "root": False,
     "subject_field": "PATIENT", "collection_id": None, "category": "allergies",
     "columns": [("START", "date"), ("STOP", "date"), ("CODE", "cat"),
                 ("DESCRIPTION", "cat")]},
    {"file": "immunizations.csv", "collection": "immunization", "root": False,
     "subject_field": "PATIENT", "collection_id": None, "category": "immunizations",
     "columns": [("DATE", "date"), ("CODE", "cat"), ("DESCRIPTION", "cat"),
                 ("BASE_COST", "float")]},
    {"file": "careplans.csv", "collection": "careplan", "root": False,
     "subject_field": "PATIENT", "collection_id": "Id", "category": "careplans",
     "columns": [("START", "date"), ("STOP", "date"), ("CODE", "cat"),
                 ("DESCRIPTION", "cat"), ("REASONDESCRIPTION", "cat")]},
    {"file": "devices.csv", "collection": "device", "root": False,
     "subject_field": "PATIENT", "collection_id": None, "category": "devices",
     "columns": [("START", "date"), ("STOP", "date"), ("CODE", "cat"),
                 ("DESCRIPTION", "cat")]},
    {"file": "imaging_studies.csv", "collection": "imaging_study", "root": False,
     "subject_field": "PATIENT", "collection_id": "Id", "category": "imaging",
     "columns": [("DATE", "date"), ("BODYSITE_DESCRIPTION", "cat"),
                 ("MODALITY_DESCRIPTION", "cat")]},
]


def pick_column(spec_col, cols):
    """A column spec may list alternates, so one layout covers naming variants."""
    candidates = spec_col if isinstance(spec_col, list) else [spec_col]
    for c in candidates:
        if c in cols:
            return c
    return None


def list_sources(root):
    """Folders under the import root that hold CSVs, so any dataset can be picked."""
    base = os.path.join(os.getcwd(), root)
    out = []
    if not os.path.isdir(base):
        return out
    for name in sorted(os.listdir(base)):
        sub = os.path.join(base, name)
        if not os.path.isdir(sub):
            continue
        csvs = [f for f in os.listdir(sub) if f.endswith(".csv")]
        if not csvs:
            continue
        known = [s["file"] for s in LAYOUT if s["file"] in csvs]
        rows = 0
        pf = os.path.join(sub, "patients.csv")
        if os.path.isfile(pf):
            rows = rows_of(pf)
        out.append({"folder": f"{root}/{name}", "name": name,
                    "csv_files": len(csvs), "recognised": len(known),
                    "patients": rows})
    return out


def emit(payload):
    print("RESULT:" + json.dumps(payload))


def columns_of(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return next(csv.reader(f), [])


def rows_of(path):
    with open(path, "rb") as f:
        return max(sum(1 for _ in f) - 1, 0)


def plan(folder):
    """What would be built. Reads the files; writes nothing."""
    base = os.path.join(os.getcwd(), folder)
    if not os.path.isdir(base):
        return {"ok": False, "error": f"No folder at {base}"}
    out, total = [], 0
    for spec in LAYOUT:
        path = os.path.join(base, spec["file"])
        entry = {"file": spec["file"], "collection": spec["collection"]}
        if not os.path.isfile(path):
            entry.update(status="missing", detail="not in this folder")
        else:
            cols = columns_of(path)
            if spec["subject_field"] not in cols:
                entry.update(status="error",
                             detail=f"no {spec['subject_field']} column")
            else:
                usable = [c for c in (pick_column(sc, cols) for sc, _ in spec["columns"]) if c]
                n = rows_of(path)
                total += n
                entry.update(status="ok", rows=n, concepts=len(usable),
                             detail=f"{n:,} rows · {len(usable)} concepts")
        out.append(entry)
    return {"ok": True, "folder": folder, "plan": out, "total_rows": total,
            "loadable": len([e for e in out if e["status"] == "ok"])}


def build(folder, unique_id, display_name):
    if Dataset.objects.filter(unique_id=unique_id).exists():
        return {"ok": False, "error": f"Project '{unique_id}' already exists. "
                                      "Pick another name."}
    base = os.path.join(os.getcwd(), folder)
    if not os.path.isdir(base):
        return {"ok": False, "error": f"No folder at {base}"}

    src_proc = Processor._base_manager.get(name="SourceCsv")
    handlers = {k: ConceptHandler._base_manager.get(name=v) for k, v in H.items()}

    created = {"collections": 0, "sources": 0, "concepts": 0}
    with transaction.atomic():
        ds = Dataset.objects.create(
            unique_id=unique_id, display_name=display_name or unique_id,
            database_name=unique_id.replace("-", "_"),
            description="Synthetic patient data (Synthea CSV layout).",
            auto_access_level="phi", autocreate_chiron_user=True,
            list_visible=True, subject_id_fields_to_index="id",
        )

        order = 0
        for spec in LAYOUT:
            path = os.path.join(base, spec["file"])
            if not os.path.isfile(path):
                continue
            cols = columns_of(path)
            if spec["subject_field"] not in cols:
                continue

            col = Collection.objects.create(
                dataset=ds, permanent_id=spec["collection"],
                name=spec["collection"], name_plural=spec["collection"] + "s",
            )
            created["collections"] += 1
            if spec["root"]:
                ds.root_collection = col
                ds.save()

            cat, _ = Category.objects.get_or_create(
                dataset=ds, unique_id=spec["category"],
                defaults={"name": spec["category"], "order": float(order + 1)})

            order += 1
            src = Source.objects.create(
                name=f"synthea_{spec['collection']}", collection=col,
                processor=src_proc, execution_order=order * 10)
            created["sources"] += 1

            args = {"filepath": f"{folder}/{spec['file']}",
                    "subject_matching_source_id_field": spec["subject_field"]}
            if spec["collection_id"]:
                args["collection_id_field"] = spec["collection_id"]
            for name, value in args.items():
                SourceProcessorArg.objects.create(source=src, name=name, value=value)

            for idx, (spec_col, kind) in enumerate(spec["columns"]):
                column = pick_column(spec_col, cols)
                if not column:
                    continue
                # permanent_id is unique across the whole install, so it carries
                # the project name.
                concept = Concept.objects.create(
                    permanent_id=f"{unique_id}__{spec['collection']}__{column}".lower()[:120],
                    name=column.replace("_", " ").lower(),
                    source=src, collection=col, category=cat,
                    concept_handler=handlers[kind], order=float(idx + 1),
                    published=True, include_in_cohort_def=True,
                    include_in_table_def=True, include_in_analysis_def=True,
                )
                ConceptHandlerArg.objects.create(concept=concept,
                                                 name="field_name", value=column)
                created["concepts"] += 1

    call_command("chiron_run_etl", unique_id, force=True)
    return {"ok": True, "dataset": unique_id, "created": created}


def csv_sources(dataset):
    return [s for s in Source.objects.filter(collection__dataset=dataset)
            if s.processor.name == "SourceCsv"]


def drop(unique_id):
    """Remove a project. Guarded: refuses the fixtures shipped with Chiron."""
    protected = {"dataset1_stored", "dataset2_stored", "dataset3_stored"}
    if unique_id in protected:
        return {"ok": False, "error": f"'{unique_id}' is a built-in fixture and "
                                      "cannot be deleted here."}
    if not Dataset.objects.filter(unique_id=unique_id).exists():
        return {"ok": False, "error": f"No project '{unique_id}'."}
    call_command("chiron_drop_dataset", unique_id, force=True)
    return {"ok": True, "dropped": unique_id}


def projects():
    """Every project, flagged so the UI knows which ones it may delete."""
    protected = {"dataset1_stored", "dataset2_stored", "dataset3_stored"}
    out = []
    for d in Dataset.objects.all().order_by("unique_id"):
        srcs = csv_sources(d)
        folder = ""
        if srcs:
            a = SourceProcessorArg.objects.filter(source=srcs[0],
                                                  name="filepath").first()
            if a:
                folder = os.path.dirname(a.value)
        out.append({"unique_id": d.unique_id, "display_name": d.display_name,
                    "sources": len(srcs), "folder": folder,
                    "deletable": d.unique_id not in protected})
    return {"ok": True, "projects": out}


def main():
    try:
        args = json.loads(os.environ.get("BUILD_ARGS", "{}"))
        action = args.get("action", "plan")
        folder = args.get("folder", "")
        if action == "projects":
            emit(projects())
        elif action == "drop":
            emit(drop(args.get("unique_id", "")))
        elif action == "sources":
            emit({"ok": True, "sources": list_sources("source_data_import")})
        elif action == "plan":
            emit(plan(folder))
        elif action == "build":
            emit(build(folder, args.get("unique_id", "synthea"),
                       args.get("display_name", "")))
        else:
            emit({"ok": False, "error": f"unknown action {action}"})
    except Exception as exc:
        emit({"ok": False, "error": f"{type(exc).__name__}: {exc}",
              "trace": traceback.format_exc()[-1000:]})


main()
