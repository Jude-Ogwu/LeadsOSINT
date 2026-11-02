"""
FastPeopleSearch (FPS) Profile Parser Module Alias
Import compatibility alias for fsp_profile_parser.py
"""
from fsp_profile_parser import parse_fsp_profile, unobfuscate_html_emails

parse_fps_profile = parse_fsp_profile

__all__ = ['parse_fsp_profile', 'parse_fps_profile', 'unobfuscate_html_emails']
