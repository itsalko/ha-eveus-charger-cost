#!/usr/bin/env bash
# Fill in the GitHub owner/repo everywhere, then make the first commit.
#   ./setup-repo.sh <github-user> [repo-name]
set -euo pipefail

owner="${1:?usage: ./setup-repo.sh <github-user> [repo-name]}"
repo="${2:-ha-eveus-charger-cost}"
url="https://github.com/$owner/$repo"

python3 - "$owner" "$repo" <<'PY'
import json, pathlib, sys

owner, repo = sys.argv[1], sys.argv[2]
url = f"https://github.com/{owner}/{repo}"

manifest = pathlib.Path("custom_components/evse_charging_cost/manifest.json")
data = json.loads(manifest.read_text())
data["documentation"] = url
data["issue_tracker"] = f"{url}/issues"
data["codeowners"] = [f"@{owner}"]
manifest.write_text(json.dumps(data, indent=2) + "\n")

readme = pathlib.Path("README.md")
text = readme.read_text()
for placeholder in (
    "https://github.com/your-user/ha-evse-charging-cost",
    "https://github.com/your-user/ha-eveus-charger-cost",
):
    text = text.replace(placeholder, url)
readme.write_text(text)
PY

git init -q
git add -A
git commit -qm "Eveus EV Charger + Cost: initial release

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
git branch -M main
git remote add origin "$url.git"

echo "Ready. Now run:"
echo "  git push -u origin main"
echo "  git tag v$(python3 -c "import json;print(json.load(open('custom_components/evse_charging_cost/manifest.json'))['version'])")"
echo "  git push --tags"
