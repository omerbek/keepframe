# Translations

UI texts live in `src/keepframe/ui/i18n.py`:

- `EN` is the source language and is complete.
- `TR` is Turkish.
- Missing keys fall back to English.

**To add a language:** copy the `TR` block, translate the values (keep the keys and the
`{placeholders}`), add it to `CATALOGS` and `LANGUAGES`, and open a pull request.
`tests/test_i18n.py` checks that every language has the same keys as English.
