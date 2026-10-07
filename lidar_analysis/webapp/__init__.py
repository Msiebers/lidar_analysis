"""Local browser-based editor for experiment_config.yaml.

Web-P1A: config_schema.py (AnalysisConfig introspection) and
config_ui_metadata.py (researcher-facing presentation metadata).
Web-P1B: config_service.py (YAML translation; validation via build_config).
Web-P1C: experiment_document.py (the whole file; load/validate/render/save).
Web-P1D: the editor itself -- app.py, templates/, form_handling.py,
pointcloud_ops_form.py, sessions.py, editor_view.py, and __main__.py
(`python -m lidar_analysis.webapp`, 127.0.0.1 only).

The editor never runs the pipeline. See README.md in this directory.
"""
