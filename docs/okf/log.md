# Bundle history

## 2026-09-15

* **Update**: KOTH states the closed stamp, one seat per player per bracket and the withdraw rule; the events module phase reads the closed stamp and keeps a scored chain running.

## 2026-09-14

* **Update**: a pass with two third-party OKF validators: the descriptions YAML misread are quoted, every concept bound to a file or a vendor carries `resource`, the runbooks carry `stale_after`, the root index carries the overview's own description, and the bundle test now checks the index lines, the tags list and unquoted values.
* **Update**: one Data Model concept per table under `data/tables/`, each listing every column with its meaning, keys and joins; `data/tables.md` becomes `data/tables/index.md`; `tests/test_okf.py` pins the columns to the concepts; the events module gains the admin's path from a new league to a finished event; the model families, GNL season and fantasy pages are corrected where they named a column the schema does not hold.
* **Update**: the events module page gains the phase rungs, the third-place rule, the previous-stage seeding guard, the drafted-teams signup rule and the check-in button rule; series reporting names the veto board's sides; the check-in hint module is renamed in scheduling and availability; KOTH names the old routes' id check.
* **Creation**: Established the bundle: conventions, concepts, data, api, runbooks, decisions and pitfalls, written from the code on `main`, the repository documents, and the maintainers' recorded decisions. Every concept is `generated` by an agent and carries no `verified` entry yet.
