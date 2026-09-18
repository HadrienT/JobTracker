"""The weekly report — blueprint/wp/WP16-feedback.md §3-4.

A markdown artifact meant to be re-read three months later to understand a drift,
so every number is dated and nothing here is "live". The last section turns the
only learning signal available — what the user favorites — into *suggestions* for
`configs/profile.yaml`. It never edits it: that file is written by hand, reviewed
in a diff, and versioned, because a profile that tunes itself makes scoring
irreproducible, which ADR-006 forbids.
"""

import sqlite3
import statistics
from datetime import datetime

from jobtracker.collect.http import SourcesConfig
from jobtracker.match.profile import Profile
from jobtracker.runtime.watchdog import full_health_snapshot
from jobtracker.store import reporting
from jobtracker.store.companies import list_discovered

# The funnel model of WP12 §2, used only to turn "N postings resolved by the LLM" into
# a rough GPU figure — the report says so.
_TOKENS_PER_CALL = 1600
_TOKENS_PER_SECOND = 40.0

_MIN_FAVORITES_FOR_LIFT = 3
_LIFT_THRESHOLD = 2.0


def profile_suggestions(
    favorites: list[reporting.FavoriteRow],
    company_lifts: list[reporting.Lift],
    tech_lifts: list[reporting.Lift],
    *,
    profile: Profile,
) -> list[str]:
    """Adjustments worth *considering*. Pure and side-effect free — nothing is applied."""
    if not favorites:
        return ["Aucun favori pour l'instant : pas de signal exploitable."]
    suggestions: list[str] = []

    off_target = [f for f in favorites if f.tier in ("stretch", "rejected")]
    if off_target:
        reasons = sorted({f.rejection_reason for f in off_target if f.rejection_reason})
        detail = f" Motifs de rejet à examiner : {', '.join(reasons)}." if reasons else ""
        suggestions.append(
            f"**{len(off_target)} favori(s) sur des offres `stretch`/`rejected`** — le filtre "
            f"écarte des offres désirables.{detail}"
        )

    median = statistics.median(f.score for f in favorites)
    if median < profile.tiers.possible:
        suggestions.append(
            f"Score médian des favoris : {median:g}, sous le seuil `possible` "
            f"({profile.tiers.possible}) — les poids sont probablement mal réglés."
        )

    for lift in company_lifts:
        if lift.favorites >= _MIN_FAVORITES_FOR_LIFT and lift.lift >= _LIFT_THRESHOLD:
            suggestions.append(
                f"Société sur-représentée : `{lift.key}` ({lift.favorites} favoris, "
                f"×{lift.lift:.1f} vs le flux) — envisager de la faire monter en rang."
            )
    for lift in tech_lifts:
        if lift.favorites >= _MIN_FAVORITES_FOR_LIFT and lift.lift >= _LIFT_THRESHOLD:
            suggestions.append(
                f"Stack sur-représentée : `{lift.key}` ({lift.favorites} favoris, "
                f"×{lift.lift:.1f}) — envisager d'en relever le poids."
            )
    return suggestions or ["Les favoris sont cohérents avec le profil : rien à ajuster."]


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_(aucune donnée)_"]
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return out


def build_weekly_report(
    conn: sqlite3.Connection,
    sources_config: SourcesConfig,
    profile: Profile,
    *,
    now: datetime,
) -> str:
    lines = [f"# Rapport hebdomadaire — {now.date()}", ""]

    companies, by_sector, by_country = reporting.coverage(conn)
    lines += ["## 1. Couverture", "", f"{companies} sociétés avec au moins une offre active.", ""]
    lines += _table(["secteur", "offres"], [[k, str(v)] for k, v in by_sector.items()])
    lines += [""]
    lines += _table(["pays", "offres"], [[k, str(v)] for k, v in list(by_country.items())[:15]])

    snapshot = full_health_snapshot(conn, sources_config, now=now)
    lines += ["", "## 2. Santé des sources", ""]
    lines += [
        f"Flux : {'**périmé**' if snapshot.feed.stale else 'frais'}, "
        f"{snapshot.feed.active_postings} offres actives.",
        "",
    ]
    lines += _table(
        ["source", "statut", "dernier run", "alerte"],
        [[str(s.source), s.status, s.last_run_at or "—", s.alert or ""] for s in snapshot.sources],
    )
    for alert in snapshot.alerts:
        lines.append(f"- ⚠ `{alert.kind}` {alert.source or ''} (depuis {alert.since})")

    silent = reporting.silent_companies(conn, now=now)
    lines += ["", "## 3. Sociétés à zéro offre depuis 30 jours", ""]
    lines += (
        [f"- `{slug}`" for slug in silent]
        + ["", "_Le signal le plus fiable d'un jeton cassé : re-sonder avec `tools/probe_ats.py`._"]
        if silent
        else ["Aucune."]
    )

    lines += ["", "## 4. Résolution du normaliseur (cohortes de 4 semaines)", ""]
    weekly = reporting.weekly_resolution(conn, now=now)
    stages = list(weekly[0].rates) if weekly else []
    lines += _table(
        ["semaine", "offres", *stages],
        [[w.week, str(w.postings), *[f"{w.rates[s] * 100:.0f}%" for s in stages]] for w in weekly],
    )

    lines += ["", "## 5. Distribution des paliers (par semaine de première détection)", ""]
    tiers = ["strong", "possible", "stretch", "rejected"]
    lines += _table(
        ["semaine", *tiers],
        [
            [w, *[str(c.get(t, 0)) for t in tiers]]
            for w, c in reporting.tiers_by_week(conn, now=now)
        ],
    )
    lines += ["", "_Si `strong` tombe à zéro, le profil est probablement trop strict._"]

    lines += ["", "## 6. Motifs de rejet (top 10)", ""]
    lines += _table(
        ["motif", "offres"], [[r, str(n)] for r, n in reporting.rejection_reasons(conn)]
    )

    resolved, queued, skipped = reporting.llm_load(conn)
    gpu = resolved * _TOKENS_PER_CALL / _TOKENS_PER_SECOND
    lines += [
        "",
        "## 7. Charge LLM",
        "",
        f"- offres tranchées par le LLM : {resolved}",
        f"- en file d'attente : {queued}",
        f"- tours sautés (serveur occupé ou éteint) : {skipped}",
        f"- ≈ {gpu:.0f} s de GPU cumulées _(estimation : les appels mis en quarantaine ne "
        "sont pas persistés)_",
    ]

    discovered = list_discovered(conn)
    lines += ["", "## 8. Employeurs inconnus du registre", ""]
    lines += _table(
        ["employeur", "slug", "offres"], [[name, slug, str(n)] for slug, name, n in discovered[:30]]
    )
    if discovered:
        lines += [
            "",
            "_À sonder avec `tools/probe_ats.py` puis ajouter à `configs/companies.yaml` (WP00)._",
        ]

    favs = reporting.favorites(conn)
    company_lifts, tech_lifts = reporting.favorite_lifts(conn)
    lines += ["", "## 9. Favoris → profil (suggestions — rien n'est appliqué)", ""]
    lines += [
        f"- {s}" for s in profile_suggestions(favs, company_lifts, tech_lifts, profile=profile)
    ]
    lines += ["", "_`configs/profile.yaml` reste écrit à la main (ADR-006)._", ""]
    return "\n".join(lines)
