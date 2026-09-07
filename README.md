# Shaoyuan Huang Homepage

Personal academic homepage for Shaoyuan Huang, built with Jekyll and the AcademicPages theme.

- Website: https://hsy23.github.io/ShaoyuanHuang/
- Repository: https://github.com/hsy23/ShaoyuanHuang
- Main configuration: `_config.yml`
- Home page content: `_pages/about.md`
- Publications: `_publications/`
- CV redirect page: `_pages/cv.md`

## Daily Maintenance

Most content updates should be made in these places:

- `_pages/about.md` for the landing page biography, news, service, awards, and selected publications.
- `_publications/*.md` for publication cards and publication detail pages.
- `_data/navigation.yml` for the top navigation.
- Root-level CV PDFs for public CV downloads.

Publication cards are rendered by `_includes/publication-card.html`. Prefer setting explicit front matter fields such as `venue_short`, `quality`, `research_areas`, `homepage`, and `paperurl` when a paper needs precise display control.

## Publication Automation

Two GitHub Actions workflows support publication updates:

- `.github/workflows/discover_publications.yml` searches for candidate publications and opens or updates a candidate PR.
- `.github/workflows/promote_publication_candidates.yml` promotes high-confidence candidates from `_publication_candidates/` into `_publications/` through a draft PR.

These workflows are intentionally conservative. Manually review title, author list, venue, URL, and acceptance status before merging promoted publication entries.

## Local Preview

Install Ruby, Bundler, and Node.js, then run:

```bash
bundle install
bundle exec jekyll serve -l -H localhost
```

The site should be available at `http://localhost:4000/ShaoyuanHuang/`.

JavaScript assets can be rebuilt with:

```bash
npm install
npm run build:js
```

## Theme

This site is based on AcademicPages, which is derived from Minimal Mistakes and released under the MIT License.
