"""
Seed the Knowledge Base Vault catalog with existing data.

Copies existing raw uploaded documents to catalog/inputs/ and
existing generated learning paths to catalog/standard_paths/.
This is a one-time migration script for the MVP.
"""

import sys
import os

# Ensure WAI_agent is importable
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from WAI_agent.shared.persistence import DepartmentScopedStore


def seed_catalog(department: str = "operations"):
    store = DepartmentScopedStore(department)

    print(f"Seeding catalog for department: {department}")
    print(f"  Catalog path: {store.catalog_path}")
    print()

    # 1. Copy raw uploaded documents → catalog/inputs/
    raw_files = store.list_raw_documents()
    print(f"Found {len(raw_files)} raw documents to copy to catalog/inputs/:")
    for filename in raw_files:
        content = store.read_raw_document(filename)
        if content:
            store.write_catalog_input(filename, content)
            print(f"  ✅ {filename}")

    # 2. Copy generated learning paths → catalog/standard_paths/
    import json
    lp_dir = store.learning_paths_path
    lp_files = list(lp_dir.glob("*.json"))
    print(f"\nFound {len(lp_files)} learning paths to copy to catalog/standard_paths/:")
    for lp_file in lp_files:
        try:
            data = json.loads(lp_file.read_text())
            path_id = data.get("path_id", lp_file.stem)
            # Add source_input_files metadata
            source_doc = data.get("source_document", "")
            if source_doc:
                data["source_input_files"] = [source_doc]
            store.write_standard_path(path_id, data)
            title = store._extract_path_title(data)
            print(f"  ✅ {path_id} — {title}")
        except Exception as e:
            print(f"  ❌ {lp_file.name}: {e}")

    # 3. Copy DTP files to catalog/inputs/ as well
    dtp_files = ["vertex_ai_dtp.json", "sample_dtp.json"]
    data_dir = store.base_path
    print(f"\nCopying DTP files to catalog/inputs/:")
    for dtp_name in dtp_files:
        dtp_path = data_dir / dtp_name
        if dtp_path.exists():
            content = dtp_path.read_text(encoding="utf-8")
            store.write_catalog_input(dtp_name, content)
            print(f"  ✅ {dtp_name}")
        else:
            print(f"  ⚠️ {dtp_name} not found at {dtp_path}")

    print("\n✅ Catalog seeding complete!")
    print(f"  Inputs:         {len(store.list_catalog_inputs())} files")
    print(f"  Standard Paths: {len(store.list_standard_paths())} paths")
    print(f"  Unofficial:     {len(store.list_unofficial_paths())} paths")
    print(f"  Gap Paths:      {len(store.list_gap_paths())} paths")


if __name__ == "__main__":
    seed_catalog()
