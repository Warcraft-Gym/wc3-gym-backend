---
type: Data Model
title: user_battle_tag
description: One battle tag a person has played under; a tag names at most one person, and each person has at most one active tag.
resource: ../../../../app/models/user_battle_tag.py
tags: [auth, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-24T11:21:07Z }
verified: { by: process:test_okf, at: 2026-09-24T10:21:07Z }
sources:
  - id: model
    resource: ../../../../app/models/user_battle_tag.py
    title: UserBattleTag
  - id: migration
    resource: ../../../../migrations/versions/e07324d2b4f9_add_the_user_battle_tag_table.py
    title: The table and its backfill from users
  - id: service
    resource: ../../../../app/services/battle_tags.py
    title: The lookup by tag and the attach step
  - id: rule
    resource: ../../../../app/core/battle_tags.py
    title: Which tags are real
  - id: routes
    resource: ../../../../app/api/routes/users.py
    title: The member tag routes, the admin move and the merge
  - id: battlenet
    resource: ../../../../app/api/routes/battlenet.py
    title: The Battle.net link routes
  - id: merge
    resource: ../../../../app/services/merge.py
    title: The merge of two people
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
- `User.battleTag` reads the active row's tag; `users` holds no copy. `set_active_tag` in `app/services/battle_tags.py` writes the flag.
- Every way in finds a person by any of their tags through this table: the member signup, an `anyone` entrant, the Twitch chat signup and withdraw, the workbook import and `GET /users/{key}`. See [users](users.md).
- A new person gets one active row. A tag new to an existing person is added and becomes active; the old rows stay. Adding a tag clears the person's [ladder_sync](ladder_sync.md) rows, so the next sync reads the new tag's seasons.
- The ladder sync reads the matches of every row and stamps each match with the row it came under. The MMR reads use only the matches of the active row; games, wins, losses and points add up across rows. See [ladder and achievements](../../concepts/ladder-and-achievements.md).
- A real tag is `Name#digits`. A stand-in gets no row and is stored nowhere: a tag ending `#GNL` and two digits, a tag that begins `Fantasy_User#` or `Review#`, and a tag with no `#`. The rule lives in `app/core/battle_tags.py`; the migration keeps a frozen copy, and a test pins the two together.

# Routes

A member manages their own tags; the session names the person. Each route answers the member's user read.

| Route | Does |
|---|---|
| `POST /users/me/tags` `{tag}` | Adds a tag the member also played as. W3Champions must know it, or 404. A new tag gets a row with source `claim`, unverified, active only when the member has no active tag. A tag held by a person with no login moves to the member with source `claim`, as below. A tag another login holds answers 409 `{"error": "<tag> belongs to another player. Ask an admin to move it."}`. |
| `PUT /users/me/tags/{tag_id}/active` | Makes one of the member's rows active; `battleTag` in the user read follows. |
| `DELETE /users/me/tags/{tag_id}` | Removes an unverified, inactive row of the member, the [w3c_ladder_matches](w3c_ladder_matches.md) stamped with it and the member's [ladder_sync](ladder_sync.md) rows. The active or a verified row answers 409. |
| `POST /users/{id}/tags/{tag_id}/move` `{to_user_id}` | Admin. Moves the row to another person with source `admin`, and answers that person. |

A row of another person is 404 to a member.

`POST /users/me/bnet/finish`, the last step of a Battle.net link (see [authentication](../../api/auth.md)), writes `bnet_account_id` on the row of the tag Blizzard names, sets its source to `link` and makes it active. A tag the member holds is marked. A tag new to the app gets a new row. A tag held by a person with no login moves to the member first, as a claim does. A tag another login holds, or an account id already on another person's row, answers 409 `{"error": "That Battle.net account or tag belongs to another player. Ask an admin."}`. A renamed Battle.net account gets a new row; the old row keeps its account id.

A row that moves, by a claim or by an admin, takes the matches stamped with it to the new person; a match the new person already holds is dropped. When the row was active, the old person's newest other row becomes active, or none and the person's `battleTag` reads null. The row is active on the new person only when they had no active row. Both people's [ladder_sync](ladder_sync.md) rows clear. `GET /users?tag_source=claim` lists the people who hold a claimed row. A merge moves every row of a person; see [users](users.md).
