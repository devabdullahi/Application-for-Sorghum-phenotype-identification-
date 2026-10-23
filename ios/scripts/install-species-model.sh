#!/bin/bash
# Installs a species model exported by model/ (`sorghum-model export --out-dir <export-dir>`)
# into the iOS app, then regenerates the Xcode project so the files are bundled.
#
#   ios/scripts/install-species-model.sh <export-dir>
#
# <export-dir> must hold exactly one traits-vN.tflite and one traits-vN.json with the same N.
# The script refuses, and changes nothing, when:
#   - either file is missing, or there is more than one of either;
#   - the two file names carry different N;
#   - the JSON's modelVersion or modelFile disagree with the file names;
#   - the JSON records a modelFileSha256 that the .tflite does not match.
# Whether the app can use the model (schema, heads, thresholds) is decided by shared/ at load
# time, not here: this only checks that the pair belongs together.
#
# Any previously installed traits-v* files are removed, so exactly one version is bundled.
# Afterwards build SorghumCapture.xcworkspace as usual.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <export-dir>" >&2
    exit 64
fi

export_dir="$1"
ios_dir="$(cd "$(dirname "$0")/.." && pwd)"
# The only place versioned model files live for iOS; project.yml bundles traits-v* from here.
models_dir="$ios_dir/SorghumCapture/Resources/Models"

refuse() {
    echo "install-species-model: $1; nothing was installed." >&2
    exit 1
}

[[ -d "$export_dir" ]] || refuse "$export_dir is not a directory"

# "._*" files are macOS metadata on exFAT drives, not model files.
models=()
metadata=()
while IFS= read -r -d '' path; do models+=("$path"); done \
    < <(find "$export_dir" -maxdepth 1 -type f -name 'traits-v*.tflite' ! -name '._*' -print0)
while IFS= read -r -d '' path; do metadata+=("$path"); done \
    < <(find "$export_dir" -maxdepth 1 -type f -name 'traits-v*.json' ! -name '._*' -print0)

[[ ${#models[@]} -eq 1 ]] || refuse "expected one traits-vN.tflite in $export_dir, found ${#models[@]}"
[[ ${#metadata[@]} -eq 1 ]] || refuse "expected one traits-vN.json in $export_dir, found ${#metadata[@]}"

model_name="$(basename "${models[0]}")"
metadata_name="$(basename "${metadata[0]}")"
model_version="${model_name#traits-v}"
model_version="${model_version%.tflite}"
metadata_version="${metadata_name#traits-v}"
metadata_version="${metadata_version%.json}"

[[ "$model_version" =~ ^[0-9]+$ ]] || refuse "$model_name does not end in a version number"
[[ "$metadata_version" =~ ^[0-9]+$ ]] || refuse "$metadata_name does not end in a version number"
[[ "$model_version" == "$metadata_version" ]] \
    || refuse "$model_name and $metadata_name have different versions"

# plutil reads JSON, so no Python is needed. Missing keys print nothing.
json_value() {
    /usr/bin/plutil -extract "$1" raw -o - "${metadata[0]}" 2>/dev/null || true
}

[[ "$(json_value modelVersion)" == "$model_version" ]] \
    || refuse "$metadata_name says modelVersion $(json_value modelVersion), expected $model_version"
[[ "$(json_value modelFile)" == "$model_name" ]] \
    || refuse "$metadata_name names modelFile $(json_value modelFile), expected $model_name"

recorded_sha256="$(json_value trainingData.modelFileSha256)"
if [[ -n "$recorded_sha256" ]]; then
    actual_sha256="$(shasum -a 256 "${models[0]}" | cut -d ' ' -f 1)"
    [[ "$actual_sha256" == "$recorded_sha256" ]] \
        || refuse "$model_name does not match the modelFileSha256 recorded in $metadata_name"
fi

mkdir -p "$models_dir"
find "$models_dir" -maxdepth 1 -name 'traits-v*' -delete
find "$models_dir" -maxdepth 1 -name '._traits-v*' -delete
# -X skips extended attributes, so macOS has nothing to write into "._" files.
cp -X "${models[0]}" "${metadata[0]}" "$models_dir/"
find "$models_dir" -maxdepth 1 -name '._*' -delete

# Same order as always: regenerating the project drops the pods' integration, pod install restores it.
(cd "$ios_dir" && xcodegen generate --quiet && pod install --silent)

echo "Installed species model v$model_version into ${models_dir#"$ios_dir/"}."
