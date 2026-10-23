# RESEARCH-Y security and source-data policy

- Repository is private; credentials, licence-protected source payloads and identifiable project content are never checked in.
- GitHub Actions runs controlled, synthetic fixtures by default; no live PubMed/Web of Science credentials are necessary or embedded in the repository.
- Later API keys must use a supported operating-system credential store and be redacted from diagnostic logs, exports and project archives (**SEC-01**, **SEC-05**).
- Future network integrations must enforce transport security, bounded retries, source licences/rate limits and source-specific limitations (**RUN-04**, **SEC-03**).
- Future archives and downloaded files must be validated for unsafe paths/filenames; migrations require backups and reliable rollback (**SEC-04**).
- All incoming changes require code-quality and security review, with a threat-oriented assessment for parsers, archives, input handling, storage and network clients.

**Current status:** No network connectors, credential handling or archive import are implemented. `.gitignore` provides a guardrail, **not** a complete secret-scanning or data-loss-prevention control. Do not place secrets in source files.

Report security concerns privately to the repository owner; do not include secrets in issues or pull requests.
