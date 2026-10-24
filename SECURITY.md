# RESEARCH-Y security and source-data policy

- Repository is **public**, including its Git history, issues and pull requests. Do not commit credentials, licence-protected source payloads, identifiable research/patient data or confidential project content, including in deleted historical commits.
- GitHub Actions runs controlled, synthetic fixtures by default; no live PubMed/Web of Science credentials are necessary or embedded in the repository.
- Later API keys must use a supported operating-system credential store and be redacted from diagnostic logs, exports and project archives (**SEC-01**, **SEC-05**).
- Future network integrations must enforce transport security, bounded retries, source licences/rate limits and source-specific limitations (**RUN-04**, **SEC-03**).
- Future archives and downloaded files must be validated for unsafe paths/filenames; migrations require backups and reliable rollback (**SEC-04**).
- All incoming changes require code-quality and security review, with a threat-oriented assessment for parsers, archives, input handling, storage and network clients.

**Current status:** No network connectors, credential handling or archive import are implemented. `.gitignore` provides a guardrail, **not** a complete secret-scanning or data-loss-prevention control. Do not place secrets in source files.

Report security concerns privately to the repository owner; do not include secrets in issues or pull requests.

Public visibility does not grant anyone permission to push or merge. Standard GitHub-hosted Actions runs use synthetic fixture data. Forked pull-request workflows must not receive secrets or elevated write permissions. The repository owner has reported enabling approval controls for external contributors; verify the effective setting in GitHub Settings → Actions → General before changing automation policies.
