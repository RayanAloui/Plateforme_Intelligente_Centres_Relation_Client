"""Plateforme de prevision, d'optimisation et de gestion des risques."""
import os

# Windows 11 recent ne fournit plus l'outil "wmic" que joblib utilise pour compter les
# coeurs physiques. joblib ne s'en passe que si LOKY_MAX_CPU_COUNT est STRICTEMENT inferieur
# au nombre de coeurs logiques : on prend la moitie, qui correspond aux coeurs physiques
# sur un processeur avec hyperthreading.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(max(1, (os.cpu_count() or 2) // 2)))