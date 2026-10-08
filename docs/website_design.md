# Public Documentation Website Design

## Understanding Summary

- Build a public GitHub Pages documentation website for open-source users,
  researchers, and friends evaluating the local workflow.
- Help visitors understand the product, install it, inspect its reliability
  controls, and reach the GitHub repository.
- Preserve the Workbench visual language: compact Inter typography, graphite
  navigation, white work surfaces, and green operational accents.
- Host only static documentation; do not expose SQLite, API credentials, paper
  text, run artifacts, or a writable Workbench.
- Publish English core documentation with one maintained Chinese quick-start
  page to avoid duplicate documentation drift.
- Deploy from `main` through GitHub Actions and validate every pull request.
- Treat public hosting of the actual Workbench as out of scope.

## Assumptions

- The site serves low-volume open-source documentation without authentication.
- GitHub Pages and Actions remain the hosting and build infrastructure.
- The repository owner maintains the site alongside the application.
- Runtime behavior and public workflow contracts do not change in v0.8.1.

## Architecture

MkDocs Material builds Markdown under `site/` into `output/site/`. A dedicated
GitHub Actions workflow runs strict builds for pull requests and deploys the
artifact for `main`. The documentation site links to canonical maintainer guides
under `docs/` when full reference material would otherwise be duplicated.

The homepage presents the real local Workbench, workflow, reliability gates,
installation path, and scope boundary. The website is a read-only documentation
surface; users run the Workbench locally.

## Validation

- Unit tests verify required navigation, version consistency, deployment
  actions, permissions, and public-content path/secret hygiene.
- `mkdocs build --strict` rejects broken configuration and references.
- Browser checks cover desktop and 320, 375, 414, and 768 pixel widths.
- The committed overview image is captured from deterministic test data.

## Decision Log

| Decision | Alternatives | Reason |
| --- | --- | --- |
| MkDocs Material | Handwritten static site; Sphinx | Best balance of maintainability, search, navigation, and technical presentation |
| English core plus Chinese quick start | English only; complete bilingual mirror | Open-source reach without doubling long-term documentation maintenance |
| Static GitHub Pages | Public Workbench deployment | Preserves the single-user local security boundary |
| Real test-data screenshot | Fabricated mockup; no product visual | Demonstrates the product without inventing capabilities or exposing user data |
