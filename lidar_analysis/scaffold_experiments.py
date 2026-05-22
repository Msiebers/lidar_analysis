#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
try:
    from .yaml_loader import yaml
    from .config import default_analysis_yaml_dict
except Exception:
    from yaml_loader import yaml
    from config import default_analysis_yaml_dict

CARTCITY_ROOT = Path('/mnt/cartcity')
EXPERIMENTS_ROOT = CARTCITY_ROOT / 'experiments'

def default_experiment_config(experiment: str) -> dict:
    return {
        'experiment_name': experiment,
        'processing_mode': 'off',
        'config_reviewed': False,
        'config_note': 'Template only. Edit this config before enabling processing.',
        'raw_data_path': f'/mnt/cartcity/raw_data/{experiment}',
        'output_path': f'/mnt/cartcity/experiments/{experiment}',
        'sharing': {'enabled': False},
        'notifications': {'enabled': False},
        'analysis': default_analysis_yaml_dict(),
    }

def ensure_experiment_scaffold(experiment: str) -> None:
    exp_root = EXPERIMENTS_ROOT / experiment
    for d in ['pointclouds','results','scan_metadata']:
        (exp_root / d).mkdir(parents=True, exist_ok=True)
    exp_config_path = exp_root / 'experiment_config.yaml'
    if not exp_config_path.exists():
        with open(exp_config_path,'w',encoding='utf-8') as f:
            yaml.safe_dump(default_experiment_config(experiment), f, sort_keys=False)

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python3 scaffold_experiments.py <experiment_name>')
    ensure_experiment_scaffold(sys.argv[1])
