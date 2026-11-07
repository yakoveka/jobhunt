---
tags:
  - job-hunt
---
# Master profile: Alex Example

> The single source of truth for every CV, cover letter and fit note. The agent may only claim what is written here.
> **[E]** = evidenced: you can point to proof (a repo, a commit count, a doc, a payslip, a public page). Say where it lives.
> **[I]** = inferred or self-reported: true to your knowledge but unproven. The agent uses [I] items only where you say so.
> Replace every example line. `/jobs setup` drafts this from your existing CV and an interview; then **you** check every line.
> You can split this across several notes (e.g. one per role); list them under `profile` in the config.

## Corrections
Read first, every time. Things that are easy to get wrong or that an old CV states wrongly. Examples:
1. The degree is "BSc Computer Science", not "MSc" (an old CV says MSc: wrong)
2. Team size at Acme was 5 engineers, not "a team of 10"
3. The 2M-requests/day figure is from after I left: don't quote it

## Identity
- Name: Alex Example · Lisbon, Portugal (UTC+0) · Portuguese citizen (EU work rights)
- Contact for CV headers: alex@example.com · +351 000 000 000 · linkedin.com/in/alex-example · github.com/alex-example
- Languages: English C1, Portuguese native, Spanish B1
- Education: BSc Computer Science, University of Somewhere, 2016 [E: diploma]

## Situation
- Why looking now, availability, notice period. e.g. "Contract at Acme ended 2026-09-30; available immediately" [E]

## Experience
One block per role, newest first. Bullets = achievements with evidence, not duties.

### Senior Backend Engineer, Acme Payments · 03/2022 – 09/2026 · remote
- Stack: Python 3.12, Django, PostgreSQL, Celery, AWS (ECS, RDS), Terraform
- Led the migration of the billing service from a monolith to three Django services; cut p95 latency from 900 ms to 250 ms [E: Grafana export in `~/evidence/acme-latency.png`]
- Mentored 3 engineers; ran the backend interview loop (~40 interviews) [I]
- On-call for payments; wrote the incident runbook used by the team [E: internal wiki page, screenshot]

### Backend Developer, Small Agency · 06/2018 – 02/2022 · Porto
- Built ~15 client sites and APIs in Django and Flask [I]

## Headline numbers
| Claim | Status | Source |
|---|---|---|
| 1,200 of 4,000 commits on the main Acme repo | [E] | `git shortlog` 2026-09-30 |
| 99.95% uptime for billing in 2025 | [I] | remembered from a status report |

## Skills matrix
Calibrated against evidence, not against CV wording.
**Strong (production, evidenced)**
- Python, Django, PostgreSQL (query tuning, migrations) [E]
- AWS (ECS, RDS, IAM), Terraform [E]
**Working (used, less depth)**
- Go: personal projects only [E: github]
- Kubernetes: course + side project, no production [E: certificate]
**Not claimed**
- Java, mobile

## Public proof
Repos, talks, articles, certificates with links.
- github.com/alex-example/some-tool: CLI for X, 300 stars [E]
