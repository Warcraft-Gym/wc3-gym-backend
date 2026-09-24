---
type: Data Model
title: user_battle_tag
description: One battle tag a person has played under; a tag names at most one person, and each person has at most one active tag.
resource: ../../../../app/models/user_battle_tag.py
tags: [auth, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-24T09:19:27Z }
verified: { by: process:test_okf, at: 2026-09-24T09:20:16Z }
sources:
  - id: model
    resource: ../../../../app/models/user_battle_tag.py
    title: UserBattleTag
  - id: migration
    resource: ../../../../migrations/versions/e07324d2b4f9_add_the_user_battle_tag_table.py
    title: The table and its backfill from users
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `user_id` | INTEGER | no | The person who holds the tag. |
| `tag` | VARCHAR | no | The battle tag, as `Name#1234`. |
| `bnet_account_id` | VARCHAR | yes | The Battle.net account behind the tag. Only a Battle.net link sets it, so a row with it set is verified. |
| `source` | VARCHAR | no | How the tag reached the person: `sheet`, `signup`, `claim`, `admin` or `link`. |
| `is_active` | BOOLEAN | no | The account the sites show for the person: its W3Champions link and MMR. |
| `first_seen` | TIMESTAMP | no | When the tag was first seen on the person, UTC. |
| `last_seen` | TIMESTAMP | no | When the tag was last seen on the person, UTC. |

# Keys and joins

Primary key `id`. Foreign key `user_id` to [users](users.md), deleted with the person. Unique expression index on `lower(trim(tag))`, so a tag names at most one person whatever its case. Partial unique index on `user_id` where `is_active`, so a person has at most one active tag. Index on `user_id`.

Pointed at by [w3c_ladder_matches](w3c_ladder_matches.md) `battle_tag_id`.

# Rules

- A person holds many tags. A season signup records the tag of that season in `user_season_signup.played_as`; see [user_season_signup](user_season_signup.md).
- `users.battleTag` holds a copy of the active row's tag.
- A real tag is `Name#digits`. Importer stand-ins get no row: a tag ending `#GNL` and two digits, a tag that begins `Fantasy_User#` or `Review#`, and a tag with no `#`.
