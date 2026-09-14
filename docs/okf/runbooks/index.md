# Runbooks

* [Back up and restore](backup-and-restore.md) - There is no scheduled backup and no restore has been run; take a pg_dump by hand before a destructive migration, and know that the workbook export is not a restore.
* [Deploy to Vercel](deploy-vercel.md) - A merge to main deploys production and migrates in the build; staging mirrors main; previews use the staging database; the Hobby plan sets the limits.
* [Run locally](run-locally.md) - Install with uv, copy the example environment, start Postgres and the backend with just, run the tests.
* [Seed a database and build a review season](seed-and-review-season.md) - Load the private seed repository into a target, or build a season two accounts can click through on staging.
* [Set up the Discord side](discord-setup.md) - Register the slash commands, upload the emojis, place the bot role, and point the channel settings rows at the right channels.
