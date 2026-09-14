---
type: Pitfall
title: Vercel CLI traps
description: "Three ways a CLI deploy goes wrong: no token, a worktree without the project link, and a commit author outside the team."
tags: [pitfall, vercel]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../just/vercel.just
    title: The Vercel recipes
---

# What happened

- A bare `npx vercel logs` with no token started a device authorization flow, which reads as an unexpected authorization prompt to whoever is watching.
- `just vercel deploy` run from a worktree found no `.vercel/` link folder (it is gitignored and lives in the main checkout), created a new project connected to the repository, and that project then tried to build every push.
- A deploy from a commit whose author is not a Vercel team member was created as blocked: `vercel ls` printed `UNKNOWN`, the log was empty, and the preview served "Deployment is building" forever.

# The rule

Run the CLI only through the recipes, only from the main checkout. For a CLI deploy, export the tree with `git archive` into a directory of the same name, copy the link file in, and deploy with `--archive=tgz`. Never change the git author to get past the block. To read why a merge did not deploy, use the commit status and the Vercel API.
