# Decisions

* [App-managed roles, manual sync](app-managed-roles.md) - Access comes from the database, Discord roles are a mirror of season facts, and the mirror updates only when an admin presses a button.
* [Ask when someone cannot play](availability-blocklist.md) - Availability is collected as blocks, blank meaning fully open, and a block informs pairings without ever constraining them.
* [Clerk owns the session](clerk-auth.md) - Members sign in through Clerk with Discord as the only social connection; the guild check and the roles stay app code.
* [Derived, not stored](derived-not-stored.md) - Every score, standing, rating and fantasy total is computed at read time; no rollup column and no recalculate button exists.
* [Discord's edit limit is a core constraint](discord-rate-limit.md) - Every channel post and edit goes through the discord_post rows, which pace edits to Discord's five per five seconds per channel and collapse a burst to its last state.
* [Draft order is a rerank, not an MMR](draft-order-rerank.md) - A hand correction to the draft order is a position on the signup row, never an adjusted MMR value.
* [GNL plays Bo3 only](bo3-only.md) - Every GNL series is a best of three; the backend keeps general best-of support, and no GNL screen offers a choice.
* [Off race per series, signup race per season](off-race-per-series.md) - A player signs up on one race for the season; a series may record a different race played on one side, stored separately from the resolved race.
* [One event model, kind modules on top](unified-event-model.md) - GNL, KOTH and community events share one data model; a kind that behaves differently gets its own module, and the shared engine never branches on kind.
* [One KOTH entrant row per race](koth-multi-entry.md) - A player may enter a KOTH night on more than one race; each race is its own entrant row, listed once on the page, and a player a series already names takes no second seat in it.
* [Pictures are URLs](pictures-as-urls.md) - Logos and map pictures live in a blob store as public URLs, uploaded from the admin UI; no bytes column exists in the database.
* [Reads open, writes admin](reads-open-writes-admin.md) - Every GET serves any session; writes need an admin or the owning member, and the frontend hides the buttons of writes a role cannot make.
* [The Discord adapter is its own small app](discord-adapter-separate.md) - Discord interactions land on a one-route Starlette app in a separate repository that verifies and forwards; the backend does the work.
* [The season boundary is manual](season-boundary-manual.md) - The W3Champions season the MMR columns read is a pinned setting, edited by hand a few times a year, never derived automatically.
* [The veto warns, it never blocks](veto-warns-never-blocks.md) - A result may be reported without a veto record, but the form makes that hard with a strong warning; each game stores its winner and its map.
* [Vercel and Supabase](vercel-and-supabase.md) - The backend runs as one Vercel function on a Supabase Postgres, and the self-hosted Azure line is frozen.
