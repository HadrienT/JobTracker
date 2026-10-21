"""The user's side of the job search — blueprint/wp/WP21-applications.md.

Reads the history the user kept by hand (a spreadsheet export, a folder of screenshots and
CVs) and reconciles it into `core.models.Application`. Imports `core` only (contract D11):
local files in, DTOs out, no network and no database.
"""
