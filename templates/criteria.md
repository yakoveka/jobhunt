---
tags:
  - job-hunt
---
# Hunt criteria (scoring rubric)

> `/jobs daily` reads this note to score every new listing. Change your targeting here, not in the skill.
> Facts about you live in your profile notes (`profile/profile.md` by default); this note holds your **preferences and rules**.
> Everything below is an example for a fictional "Alex Example". Replace it with your own (`/jobs setup` does this with you).
> Tip: when you make a decision ("not Germany", "skip anything asking for a video"), add it here with the date, so the agent applies it from then on.

## Goal
- What you want and by when: e.g. "a full-time remote backend role by 2027-03-01". The dashboard deadline lives in the config (`[goal]`)
- **Volume**: how many tailored drafts per day you can realistically review and send (e.g. 3–5)
- **Money**: floor **$4,000/month net**, target **$6,000+/month net**. State the currency and whether it's net or gross
- Net vs gross rules for your situation, so the agent can compare listings (e.g. "contractor pay to my country: gross ≈ net minus 10% tax"; "employment in country X: net ≈ 65% of gross"). Mark anything you haven't verified as unverified

## In scope
| Family | Notes |
|---|---|
| Senior backend (Python / Django) | Strongest evidence. Score these up |
| Platform / DevOps | Docker, Terraform, AWS. No production Kubernetes: K8s-heavy roles = gap |
| Engineering manager | Only with a hands-on component |

**Domains**: which industries are fine and which are not (e.g. "anything legal except gambling and defence").
**Work modes**: e.g. "remote from Lisbon, Portugal (UTC+0), contract or employment; relocation within the EU only with sponsorship"; time-zone overlap limits.
**Languages**: which languages you can work in. Listings in another language you speak → CV and cover letter in that language.

## Hard no (score 0, list under "Skipped")
- Requires citizenship, work authorisation or residence you lack, with no sponsorship
- Seniority you don't want (e.g. junior/intern); stacks you won't work in (e.g. "Java primary")
- Clearly below the floor
- Application processes you refuse (e.g. recorded video, unpaid take-home over 4 hours)

## Score (0–100)
Start at 50, then adjust:
- **Stack match** with the Strong skills in your profile's skills matrix: +0…+25
- **Seniority match**: +0…+10. Stretch roles (e.g. Staff at big-tech scale): −5
- **Pay**: stated ≥ target +10; between floor and target +5; unknown 0; borderline −10
- **Location / work-mode fit**: explicitly allows where you are: +10; relocation + sponsorship to a place you want: +10; vague: 0
- **Fresh** (≤ 3 days) +5. **Direct company posting** (ATS) +5 vs agency/marketplace −5
- **Gaps** that would surface in screening: −5 each
- **Already applied** to the same company in the last 60 days: skip (note it)

**Draft threshold**: ≥ 70. Draft the top 3–5 per day (fewer if fewer pass); list the 70+ leftovers as "next up".

## CV rules (non-negotiable)
Rules the agent must follow in every CV and cover letter. Examples:
- Only [E] claims from the profile, plus [I] claims the profile explicitly clears. Follow every item under **Corrections** in the profile
- How to name a confidential employer (e.g. "Fintech scale-up (under NDA)": never the real name)
- Things never to state (e.g. "don't mention the 2024 career break unless the form asks"; "never state hours per week")
- Location line per work mode: remote roles "Lisbon, Portugal (UTC+0) · Remote · Contract or employment"; relocation roles "Open to relocation · Requires EU work sponsorship"
- Skills to downplay honestly (e.g. "Go = personal projects only")

## Ready answers
Answers the agent reuses in fit notes and application forms:
- **Why available now**: one neutral sentence
- **Notice period**: e.g. "available immediately" / "4 weeks"
- **Salary question in forms**: e.g. "ask for the band first; otherwise $6k/month net (contract). Never below the floor"
- **Gaps or unusual history**: the honest one-liner you're comfortable with
