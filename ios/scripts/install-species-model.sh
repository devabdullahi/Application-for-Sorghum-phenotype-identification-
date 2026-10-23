#!/bin/bash
# Installs a species model exported by model/ (`sorghum-model export --out-dir <export-dir>`)
# into the iOS app, then regenerates the Xcode project so the files are bundled.
#
#   ios/scripts/install-species-model.sh <export-dir>
#
# The installed traits-vN.tflite and traits-vN.json are committed to git (plain git, no LFS;
# about 1-2 MB), so every checkout bundles the model and the R7 parity test runs everywhere.
# Commit them together with the matching fixtures in shared/src/commonTest/resources/species/.
#
# <export-dir> must hold exactly one traits-vN.tflite and one traits-vN.json with the same N.
# The script refuses, and changes nothing, when:
#   - xcodegen or pod is not installed;
#   - either file is missing, or there is more than one of either;
#   - the two file names carry different N;
#   - the JSON's modelVersion or modelFile disagree with the file names;
#   - the JSON records no trainingData.modelFileSha256, or the .tflite does not match it.
# Whether the app can use the model (schema, heads, thresholds) is decided by shared/ at load
# time, not here: this only checks that the pair belongs together.
#
# The new pair is staged next to the installed models and moved into place before any older
# traits-v* files are removed, so a failed copy leaves the previous model installed.
# Afterwards build SorghumCapture.xcworkspace as usual; after installing a lower N than before,
# do a clean build (see the message at the end).

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "usage: $0 <export-dir>" >&2
    exit 64
fi

export_dir="$1"
ios_dir="$(cd "$(dirname "$0")/.." && pwd)"
# The only place versioned model files live for iOS; project.yml bundles traits-v* from here.
models_dir="$ios_dir/SorghumCapture/Resources/Models"

# Prints why the export was rejected and stops. Only for checks that run before anything in
# models_dir is touched, so the message can promise that nothing was installed.
refuse() {
    echo "install-species-model: $1; nothing was installed." >&2
    exit 1
}

# Checked first so a missing tool cannot leave new model files with a stale Xcode project.
for tool in xcodegen pod; do
    command -v "$tool" >/dev/null || refuse "$tool is not installed (needed to regenerate the Xcode project)"
done

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

# Required: without it nothing ties the .tflite to the metadata that describes it.
recorded_sha256="$(json_value trainingData.modelFileSha256)"
[[ -n "$recorded_sha256" ]] || refuse "$metadata_name records no trainingData.modelFileSha256"
actual_sha256="$(shasum -a 256 "${models[0]}" | cut -d ' ' -f 1)"
[[ "$actual_sha256" == "$recorded_sha256" ]] \
    || refuse "$model_name does not match the modelFileSha256 recorded in $metadata_name"

mkdir -p "$models_dir"

# Highest version installed before this run, to warn about stale files in incremental builds.
previous_version=0
for installed in "$models_dir"/traits-v*.json; do
    [[ -e "$installed" ]] || continue
    installed_version="$(basename "$installed" .json)"
    installed_version="${installed_version#traits-v}"
    if [[ "$installed_version" =~ ^[0-9]+$ ]] && (( installed_version > previous_version )); then
        previous_version="$installed_version"
    fi
done

# Staged inside models_dir so the final mv is a rename on the same volume.
staging_dir="$(mktemp -d "$models_dir/.install.XXXXXX")"
trap 'rm -rf "$staging_dir"' EXIT
# -X skips extended attributes, so macOS has nothing to write into "._" files.
cp -X "${models[0]}" "${metadata[0]}" "$staging_dir/"
mv -f "$staging_dir/$model_name" "$staging_dir/$metadata_name" "$models_dir/"

# Only now that the new pair is in place are other versions removed.
find "$models_dir" -maxdepth 1 -name 'traits-v*' ! -name "$model_name" ! -name "$metadata_name" -delete
find "$models_dir" -maxdepth 1 -name '._*' -delete

trap 'echo "install-species-model: traits-v$model_version is in place, but regenerating the Xcode project failed; fix the error above, then run: cd ios && xcodegen generate && pod install" >&2' ERR
# Same order as always: regenerating the project drops the pods' integration, pod install restores it.
# Plain commands, not a subshell: macOS bash 3.2 does not run the ERR trap when a subshell fails.
cd "$ios_dir"
xcodegen generate --quiet
pod install --silent
trap - ERR

echo "Installed species model v$model_version into ${models_dir#"$ios_dir/"}."
if (( previous_version > model_version )); then
    # An incremental build leaves the old traits-v$previous_version files in the built app, and
    # the app loads the highest version it finds.
    echo "Clean build after installing a lower version: v$previous_version was installed before (Xcode: Product > Clean Build Folder)."
fi
