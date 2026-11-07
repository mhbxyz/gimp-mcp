#!/usr/bin/env bash
# Install the built wheel in a clean container of one distribution and run the smoke test.
#   ci/run-distro.sh ubuntu-26.04 [path/to/gimp_mcp-*.whl]
set -euo pipefail
cd "$(dirname "$0")/.."
id=$1
wheel=${2:-}
spec=$(python3 -c "import json,sys; d={x['id']:x for x in json.load(open('ci/distros/distros.json'))['distributions']}; x=d[sys.argv[1]]; assert x['status']=='supported', x['id']+' is not supported'; print(json.dumps(x))" "$id")
image=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['image'])" "$spec")
install=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['install'])" "$spec")
tag="gimp-mcp-distro-$id"
docker build -q -f ci/distros/Dockerfile --build-arg "BASE_IMAGE=$image" --build-arg "INSTALL=$install" -t "$tag" ci/distros >/dev/null
if [ -z "$wheel" ]; then
  rm -rf dist-distro && uv build -q --wheel --out-dir dist-distro && wheel=$(ls dist-distro/*.whl)
fi
chmod -R a+rX "$(dirname "$wheel")" ci/distros  # the container user may have another uid
mkdir -p ci-artifacts && chmod 777 ci-artifacts
docker run --rm -v "$PWD/$(dirname "$wheel")":/dist:ro -v "$PWD/ci/distros":/smoke:ro -v "$PWD/ci-artifacts":/artifacts "$tag" sh -euc '
  uv venv -q --python 3.12 /tmp/venv
  uv pip install -q --python /tmp/venv/bin/python /dist/*.whl
  /tmp/venv/bin/python /smoke/smoke.py | tee "/artifacts/distro-'"$id"'.json"
'
