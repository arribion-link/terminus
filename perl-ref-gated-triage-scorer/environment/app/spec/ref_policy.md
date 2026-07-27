# Model Ref Verification Policy v2

## Source repository

The model repository is a local bare git directory at `/srv/model-repo.git`.

For each scoring request, the worker must clone or fetch from this directory to resolve the requested `model_ref` and retrieve the model coefficients.

## Resolution rules

The `model_ref` field from the request is a free-form string. The worker must classify it as follows:

### 1. Pinned commit SHA — 40 lowercase hex characters

If `model_ref` matches `^[0-9a-f]{40}$`:
- Clone `/srv/model-repo.git`.
- Determine the set of **advertised** commit SHAs: the set of object IDs obtained by peeling every ref in `refs/heads/*` and `refs/tags/*` to a commit (`<ref>^{commit}`). For an annotated tag object, the peeled commit is used; the tag object SHA itself is not included unless it also happens to be a commit.
- **Accept** if the requested SHA is in this advertised set.
- **Reject** with `REF_MISMATCH` if the SHA exists in the repository's object store but is not advertised (e.g., a dangling commit).
- Short SHAs (7–39 hex) or mixed-case SHAs are not pinned — they are rejected as `UNPINNED_REF` (see below).

### 2. Annotated tag name — `v<MAJOR>.<MINOR>.<PATCH>`

If `model_ref` matches `^v\d+\.\d+\.\d+$`:
- Clone `/srv/model-repo.git`.
- Check whether `refs/tags/<model_ref>` exists.
- Check the object type with `git cat-file -t refs/tags/<model_ref>`.
  - If the type is `tag` (annotated), **accept** it. The resolved commit is the peeled commit (`refs/tags/<model_ref>^{commit}`). Return `ref_kind: "tag"`.
  - If the type is `commit` (lightweight tag), **reject** with `UNPINNED_REF`. Lightweight tags are not accepted.
- If the tag does not exist, reject with `UNPINNED_REF`.

### 3. Everything else — rejected as unpinned

Any `model_ref` that does not match case 1 or case 2 — including branch names, short SHAs, remote-tracking patterns, symrefs, `HEAD`, case-variant SHAs — must be rejected with `UNPINNED_REF`.

## Caching

The worker MAY cache the cloned repository across requests to avoid repeated cloning. If caching is implemented, the cache must be keyed by repository path (`/srv/model-repo.git`) and must be verified to still point to the same on-disk repository. Caching is not required.

## Model file retrieval

Once the commit is resolved and verified, load `model.json` from the repository root at that commit using `git show <commit>:model.json`.
