from PyQt6.QtCore import QObject, pyqtSignal


class AppState(QObject):
    """Centralized state management for the password manager application.

    Replaces scattered state variables in MainWindow with a single QObject
    that emits signals when any state changes, allowing other components
    to react without tight coupling.
    """

    # Signals
    view_mode_changed = pyqtSignal(str)      # 'default' | 'search' | 'ai_highlight'
    vault_changed = pyqtSignal(str)           # 'accounts' | 'urls'
    category_changed = pyqtSignal(str)        # current category name
    selection_mode_changed = pyqtSignal(bool)
    highlight_changed = pyqtSignal(object)    # set of matched IDs or None
    cache_dirty_changed = pyqtSignal(str)     # 'accounts' | 'urls' | 'both'
    session_version_changed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        # View state
        self._view_mode = 'default'           # 'default' | 'search' | 'ai_highlight'
        self._current_vault = 'accounts'      # 'accounts' | 'urls'
        self._current_category = '全部'

        # Selection state
        self._selection_mode = False
        self._selected_ids = set()            # set of int IDs

        # AI highlight state
        self._highlight_matched_ids = None    # set of int or None
        self._highlight_reasoning = ""

        # Cache state
        self._cache_dirty_accounts = True
        self._cache_dirty_urls = True
        self._cached_accounts = []
        self._cached_urls = []

        # Category reload flag
        self._categories_need_reload = False

        # Session version (increment to invalidate dependent state)
        self._session_version = 0

    # ── view_mode ─────────────────────────────────────────────────
    @property
    def view_mode(self):
        return self._view_mode

    @view_mode.setter
    def view_mode(self, value):
        if self._view_mode != value:
            self._view_mode = value
            self.view_mode_changed.emit(value)

    # ── current_vault ─────────────────────────────────────────────
    @property
    def current_vault(self):
        return self._current_vault

    @current_vault.setter
    def current_vault(self, value):
        if self._current_vault != value:
            self._current_vault = value
            self.vault_changed.emit(value)

    # ── current_category ──────────────────────────────────────────
    @property
    def current_category(self):
        return self._current_category

    @current_category.setter
    def current_category(self, value):
        if self._current_category != value:
            self._current_category = value
            self.category_changed.emit(value)

    # ── highlight_matched_ids ─────────────────────────────────────
    @property
    def highlight_matched_ids(self):
        return self._highlight_matched_ids

    @highlight_matched_ids.setter
    def highlight_matched_ids(self, value):
        if self._highlight_matched_ids != value:
            self._highlight_matched_ids = value
            self.highlight_changed.emit(value)

    # ── highlight_reasoning ───────────────────────────────────────
    @property
    def highlight_reasoning(self):
        return self._highlight_reasoning

    @highlight_reasoning.setter
    def highlight_reasoning(self, value):
        self._highlight_reasoning = value

    # ── selection_mode ────────────────────────────────────────────
    @property
    def selection_mode(self):
        return self._selection_mode

    @selection_mode.setter
    def selection_mode(self, value):
        if self._selection_mode != value:
            self._selection_mode = value
            self.selection_mode_changed.emit(value)

    # ── selected_ids ──────────────────────────────────────────────
    @property
    def selected_ids(self):
        return self._selected_ids

    def add_selected_id(self, id_val):
        self._selected_ids.add(id_val)

    def remove_selected_id(self, id_val):
        self._selected_ids.discard(id_val)

    def clear_selected_ids(self):
        self._selected_ids.clear()

    # ── session_version ───────────────────────────────────────────
    @property
    def session_version(self):
        return self._session_version

    def inc_session_version(self):
        self._session_version += 1
        self.session_version_changed.emit(self._session_version)

    # ── cache helpers ─────────────────────────────────────────────
    def mark_cache_dirty(self, vault='both'):
        """Mark one or both vault caches as dirty, emitting cache_dirty_changed."""
        if vault in ('accounts', 'both'):
            self._cache_dirty_accounts = True
        if vault in ('urls', 'both'):
            self._cache_dirty_urls = True
        self.cache_dirty_changed.emit(vault)

    def is_cache_dirty(self, vault='accounts'):
        """Check if the cache for *vault* is stale."""
        return self._cache_dirty_accounts if vault == 'accounts' else self._cache_dirty_urls

    def get_cached(self, vault='accounts'):
        """Return the cached list for *vault*."""
        return self._cached_accounts if vault == 'accounts' else self._cached_urls

    def set_cached(self, vault, data):
        """Set the cached data for *vault* and clear its dirty flag.

        Does NOT emit itself — callers that need a signal should use
        mark_cache_dirty / set_cached together.
        """
        if vault == 'accounts':
            self._cached_accounts = data
            self._cache_dirty_accounts = False
        else:
            self._cached_urls = data
            self._cache_dirty_urls = False

    # ── categories reload flag ────────────────────────────────────
    def mark_categories_need_reload(self):
        self._categories_need_reload = True

    def clear_categories_need_reload(self):
        self._categories_need_reload = False

    def needs_categories_reload(self):
        return self._categories_need_reload
