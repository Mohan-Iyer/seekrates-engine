# Seekrates AI - Production Runtime

MINIMAL deployment - runtime files only.

**Excluded from deployment:**
- Session state files (re_anchor_*.yaml)
- DNA validation reports (cascade_reports_*.yaml)
- Debug documents (debug_and_report*.yaml)
- Test files (test_*.py)
- Development tools (validate_*, parse_*, detect_*, generate_*)
- Development documentation (directory_map.yaml)

**File count:** ~40 essential runtime files

**Environment variables required:**
- Set in Railway dashboard (not in code)
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION
- FERNET_KEY, EMAIL_PASSWORD

**Deployment:** Automatic via GitHub push to main branch
