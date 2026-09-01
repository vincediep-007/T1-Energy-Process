# CHANGELOG

## [v5.9] - 2026-01-08
### Added
-   **Modern UI**: Complete flat design overhaul with custom `ModernButton`, `ModernEntry`, and `SelectableLabel` widgets.
-   **Optimization**: Multi-threaded image search using `ThreadPoolExecutor`.
-   **Navigation**: New top-bar navigation for switching between multiple Serial Numbers.
-   **Export**: functionality to export search results to CSV.
-   **Date Picker**: Custom calendar widget replacement for standard date entry.
-   **Config**: Centralized `config.py` for all settings.

### Changed
-   Refactored `ImageSearchEngine` for better performance and cancellation support.
-   Moved history storage to `search_history_v5.json`.
-   Updated branding to "PreEL Viewer Dashboard".

### Fixed
-   Scrollbar visibility and mousewheel scrolling in result area.
