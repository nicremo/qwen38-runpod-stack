#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$TMP_DIR/bin"

cat > "$TMP_DIR/bin/runpodctl" <<'MOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == "pod" && "${2:-}" == "create" && "${3:-}" == "--help" ]]; then
    if [[ "${MOCK_TIMER_SUPPORTED:-0}" == "1" ]]; then
        echo "      --terminate-after string   terminate the pod at an ISO timestamp"
    else
        echo "      --name string              pod name"
    fi
    exit 0
fi
printf '%s\n' "$@"
MOCK

cat > "$TMP_DIR/bin/date" <<'MOCK'
#!/usr/bin/env bash
echo '2030-01-02T03:04:05Z'
MOCK

chmod +x "$TMP_DIR/bin/runpodctl" "$TMP_DIR/bin/date"

run_rp() {
    PATH="$TMP_DIR/bin:$PATH" \
    RUNPODCTL_BIN="$TMP_DIR/bin/runpodctl" \
    "$ROOT/bin/rp" "$@" 2>&1
}

assert_contains() {
    local output="$1" expected="$2"
    grep -Fq -- "$expected" <<<"$output" || {
        echo "expected output to contain: $expected" >&2
        echo "$output" >&2
        exit 1
    }
}

assert_not_contains() {
    local output="$1" unexpected="$2"
    if grep -Fq -- "$unexpected" <<<"$output"; then
        echo "expected output not to contain: $unexpected" >&2
        echo "$output" >&2
        exit 1
    fi
}

assert_not_line() {
    local output="$1" unexpected="$2"
    if grep -Fxq -- "$unexpected" <<<"$output"; then
        echo "expected output not to contain line: $unexpected" >&2
        echo "$output" >&2
        exit 1
    fi
}

supported=$(MOCK_TIMER_SUPPORTED=1 run_rp pod create --name demo)
assert_contains "$supported" '--terminate-after'
assert_contains "$supported" '2030-01-02T03:04:05Z'

supported_long=$(MOCK_TIMER_SUPPORTED=1 run_rp 6h pod create --name demo)
assert_contains "$supported_long" 'keep-demo'

unsupported=$(MOCK_TIMER_SUPPORTED=0 run_rp pod create --name demo)
assert_contains "$unsupported" 'relying on the local reaper'
assert_not_line "$unsupported" '--terminate-after'

unsupported_long=$(MOCK_TIMER_SUPPORTED=0 run_rp 6h pod create --name demo)
assert_contains "$unsupported_long" 'the reaper will still enforce its 1h limit'
assert_not_contains "$unsupported_long" 'keep-demo'
assert_not_line "$unsupported_long" '--terminate-after'

echo "test-rp: ok"
