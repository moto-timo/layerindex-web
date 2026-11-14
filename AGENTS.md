# AGENTS.md — layerindex-web

Guidance for AI agents working in the `layerindex-web` repository: the
OpenEmbedded Layer Index (`layerindex/`) and the Recipe Reporting System
(`rrs/`), a Django application.

## Shared OpenEmbedded rules

The rules in this section come from OpenEmbedded-Core's `AGENTS.md`
(added in openembedded-core commit 06d397a09e, "AGENTS.md: Add file"),
adapted only where layerindex-web differs. If they change there, update
them here too.

### Making changes

- No web PR workflow. The project uses **patches on mailing lists**
  (yocto-patches@lists.yoctoproject.org, with `[layerindex-web]` in the
  subject) tracked via patchwork. Don't assume GitHub PR conventions apply.
  `README.md` shows how to set up `git send-email` for this.
- One Git commit per logical change.
- Commit message format:
  - Summary line prefixed with the short file path or component,
    e.g. `layerindex/models.py: store long recipe values without truncating`
    or `dockersetup.py: use "docker compose" when it is available`.
    Check `git log --oneline <path>` for the prefix convention already in use.
  - Body explains what/why/how, and how it was tested.
  - Prefer explaining *why* a change was made over restating what's
    already visible in the diff, unless the diff is long/hard to follow
    or the reason for the change isn't known — in those cases, summarize
    what changed instead.
  - Be succinct: use as few sentences and lines as possible while still
    covering what/why/how. Cut restatements, filler, and any detail a
    reviewer wouldn't need (e.g. exact test-run counts, step-by-step
    narration). One short paragraph is usually enough; only add a second
    if a distinct point (e.g. testing) needs it.
  - The most relevant information about the change should be presented first.
  - Reference bugs as `[YOCTO #1234]` when applicable. Layer index and RRS
    bugs are in the "Layer Index" and "Recipe Reporting System (RRS)"
    products on bugzilla.yoctoproject.org.
  - Use `Reported-by`, `Suggested-by`, `Tested-by`, `Reviewed-by`, `Cc` tags
    where relevant.

### AI-generated code

- **Mandatory**: any AI-generated code/commit must add an `AI-Generated:`
  tag line in the commit message, placed *before* `Signed-off-by` (if present),
  naming the tool used, e.g.:

  ```
  component: Add the ability to ...

  AI-Generated: Uses GitHub Copilot
  ```

- Also add a code comment or other in-patch indication that the code is
  AI-generated (recommended, not just the commit tag).
- **Mandatory** Do not automatically add a `Signed-off-by`. This tag must
  always be written by the human contributor, never by the AI tool — the
  DCO/Developer's Statement of Origin still applies in full. Don't commit
  with `git commit -s` on the contributor's behalf.
- Contributor is responsible for confirming the AI tool's terms don't
  conflict with the project's open source license/IP policy, and that
  any third-party copyrighted material in the AI output is properly
  licensed before contributing it. See the Linux Foundation generative AI
  guidance: https://www.linuxfoundation.org/legal/generative-ai.
- `Co-authored-by` should be omitted in favor of the `AI-Generated` tag.

When in doubt about a convention, grep `git log --oneline <path>` in the
target repo for precedent before inventing a new style.

## layerindex-web specifics

### Branches

- Send patches against `master`.
- `master-next` is a staging branch for maintainers only. Don't base work
  on it or target it unless a maintainer asks.
- The GitHub repository is a mirror. Its CI (`.github/workflows/ci.yml`)
  runs on pushes to `master` and `master-next` and on pull requests against
  `master`; contributions still go to the mailing list.

### Testing

- Run the full suite as CI does with `docker/run-tests.sh`: it builds the
  Docker image and runs pytest against a throwaway MariaDB.
- Development and test tools (pytest, pytest-django, ruff) are pinned in
  `requirements-dev.txt`. `README.devel.md` describes the dev container and
  running the tests without Docker.
- New code comes with tests in `tests/` that cover its behaviour.
- A bug fix comes with a test that fails without the fix and passes with
  it, so the test proves the fix solves the reported problem. Check this
  by running the new test against the code before the fix.
- Where a test isn't practical (e.g. the bug needs a real BitBake parse or
  network access), say in the commit message how the fix was tested
  instead.

### Code layout and pitfalls

- Models change through Django migrations. Generate them with
  `python3 manage.py makemigrations`, don't write them by hand, and commit
  each with the model change that needs it. Migrations are numbered
  (`layerindex/migrations/00NN_*.py`, `rrs/migrations/00NN_*.py`); if a
  series is based on another unmerged series that adds a migration, say so
  in the cover letter.
- There are two settings files: `settings.py` (local development) and
  `docker/settings.py` (the Docker image). A new setting usually needs to go
  in both.
- `conf/local.conf` is the BitBake configuration for every recipe parse
  done by layer index updates (`layerindex/update.py`, `update_layer.py`)
  and by the RRS tools (`rrs/tools/`). A change there affects all of them
  and every OE-Core revision they parse, including old ones that RRS
  replays.
- The update scripts check out BitBake and layer branches in the shared
  fetch directory (`LAYER_FETCH_DIR`) before parsing. Don't assume a
  repository there is on the branch being processed unless the code checks
  it out.
- Keep unrelated reformatting out of a change; `ruff.toml` preserves the
  existing quote style.
