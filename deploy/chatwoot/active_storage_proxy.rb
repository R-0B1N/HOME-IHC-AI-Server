# frozen_string_literal: true
# Ensure ActiveStorage resolves URLs to permanent proxy mode.
# Prevents mobile WebView and iOS QuickLook / Android PDF Viewer 302 redirect token expiration failures (HTTP 404/401).
Rails.application.config.active_storage.resolve_model_to_route = :rails_storage_proxy
