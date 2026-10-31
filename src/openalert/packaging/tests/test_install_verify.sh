#!/usr/bin/env bash
# Isolated packaging regressions: never run the privileged installer or a daemon.
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGING_DIR="$(cd "${TEST_DIR}/.." && pwd)"
WORK_DIR="$(mktemp -d "${TEST_DIR}/.install-verify.XXXXXX")"
trap 'rm -rf -- "${WORK_DIR}"' EXIT
PASS_COUNT=0
FAIL_COUNT=0

assert_contains() {
    local content
    content="$(<"$1")"
    [[ "${content}" == *"$2"* ]] || {
        printf 'Expected %s to contain: %s\n' "$1" "$2" >&2
        return 1
    }
}

assert_not_contains() {
    local content
    content="$(<"$1")"
    [[ "${content}" != *"$2"* ]] || {
        printf 'Unexpected text in %s: %s\n' "$1" "$2" >&2
        return 1
    }
}

run_test() {
    local status=0
    set +e
    (set -e; "$@")
    status=$?
    set -e
    if [[ "${status}" -eq 0 ]]; then
        printf 'PASS %s\n' "$1"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        printf 'FAIL %s\n' "$1" >&2
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

prepare_source_fixture() {
    export FIXTURE="${WORK_DIR}/$1/source tree/src/openalert"
    export TRACE="${WORK_DIR}/$1/trace"
    mkdir -p "${FIXTURE}/packaging" "${FIXTURE}/templates"
    : > "${FIXTURE}/Cargo.toml"
    : > "${FIXTURE}/Cargo.lock"
    : > "${FIXTURE}/templates/alert.tera"
    : > "${TRACE}"

    # Extract only lookup/build/template sections; omit root checks and all
    # account, install, service, configuration and optional Wi-Fi actions.
    awk '
        /^set -euo pipefail/ { print }
        /^log_[a-z]+\(\)/ { print }
        /^SCRIPT_DIR=/ { selected = 1 }
        /^# 3\./ { selected = 0 }
        /^# 6\./ { selected = 1 }
        /^# 7\./ { selected = 0 }
        selected { print }
    ' "${PACKAGING_DIR}/install.sh" > "${FIXTURE}/packaging/install.sh"
    export RED='' GREEN='' YELLOW='' BLUE='' NC=''

    cargo() {
        [[ "${PWD}" == "${FIXTURE}" ]] || return 90
        printf 'cargo cwd=%s args=%s\n' "${PWD}" "$*" >> "${TRACE}"
        mkdir -p target/release
        : > target/release/openalertd
    }
    cp() { printf 'cp <%s>\n' "$@" >> "${TRACE}"; }
    chown() { printf 'chown <%s>\n' "$@" >> "${TRACE}"; }
    chmod() { printf 'chmod <%s>\n' "$@" >> "${TRACE}"; }
    export -f cargo cp chown chmod
}

test_source_build_lookup() {
    prepare_source_fixture source-build
    bash "${FIXTURE}/packaging/install.sh" > "${WORK_DIR}/source-build/output" 2>&1 || return 1
    assert_contains "${TRACE}" "cargo cwd=${FIXTURE} args=build --release --locked" || return 1
    assert_contains "${TRACE}" "cp <${FIXTURE}/templates/alert.tera>"
}

test_source_template_lookup() {
    prepare_source_fixture source-templates
    mkdir -p "${FIXTURE}/target/release"
    : > "${FIXTURE}/target/release/openalertd"
    bash "${FIXTURE}/packaging/install.sh" > "${WORK_DIR}/source-templates/output" 2>&1 || return 1
    assert_contains "${TRACE}" "cp <${FIXTURE}/templates/alert.tera>" || return 1
    assert_not_contains "${TRACE}" 'cargo '
}

test_bundle_without_builder_helpers() {
    prepare_source_fixture bundle
    mkdir -p "${FIXTURE}/packaging/bin" "${FIXTURE}/packaging/templates"
    : > "${FIXTURE}/packaging/bin/openalertd"
    : > "${FIXTURE}/packaging/templates/bundled.tera"
    rm -- "${FIXTURE}/Cargo.toml" "${FIXTURE}/Cargo.lock"
    bash "${FIXTURE}/packaging/install.sh" > "${WORK_DIR}/bundle/output" 2>&1 || return 1
    assert_contains "${TRACE}" "cp <${FIXTURE}/packaging/templates/bundled.tera>" || return 1
    assert_not_contains "${TRACE}" 'cargo '
}

test_source_without_lockfile() {
    prepare_source_fixture no-lock
    rm -- "${FIXTURE}/Cargo.lock"
    if bash "${FIXTURE}/packaging/install.sh" > "${WORK_DIR}/no-lock/output" 2>&1; then
        return 1
    fi
    assert_contains "${WORK_DIR}/no-lock/output" 'Cargo.lock'
    assert_not_contains "${TRACE}" 'cargo '
}

test_source_build_failure() {
    prepare_source_fixture failed-build
    cargo() { return 17; }
    export -f cargo
    if bash "${FIXTURE}/packaging/install.sh" > "${WORK_DIR}/failed-build/output" 2>&1; then
        return 1
    fi
    assert_not_contains "${TRACE}" 'cp '
    cargo() { return 0; }
    export -f cargo
    if bash "${FIXTURE}/packaging/install.sh" > "${WORK_DIR}/failed-build/output" 2>&1; then
        return 1
    fi
    assert_contains "${WORK_DIR}/failed-build/output" 'Build did not produce'
    assert_not_contains "${TRACE}" 'cp '
}

prepare_verify_fixture() {
    export FIXTURE="${WORK_DIR}/$1/instance with spaces"
    export TRACE="${WORK_DIR}/$1/trace"
    export VERIFY_OUTPUT="${WORK_DIR}/$1/output"
    mkdir -p "${FIXTURE}/stubs" "${FIXTURE}/config" "${FIXTURE}/templates" \
        "${FIXTURE}/state" "${FIXTURE}/logs" "${FIXTURE}/bin"
    : > "${FIXTURE}/config/instance.toml"
    : > "${TRACE}"
    export CHECK_EXIT=0 CURL_EXIT=0 HTTP_STATUS=200
    export HEALTH_BODY='{"status":"ok","uptime_seconds":42,"private":"SECRET_BODY"}'
    export CALLER_UID=0 CALLER_USER=fixture-admin CALLER_GROUP=fixture-admin
    export ACCOUNT_UID=1001 ACCOUNT_MISSING=0 GROUP_MISSING=0 ACCESS_FAIL=0
    export UNIT_LOAD_STATE=loaded UNIT_ACTIVE=0 AS_SERVICE=0
    export RUNUSER_NAME=fixture-svc RUNUSER_GROUP=fixture-group

    # All external host/account/service/network actions are intercepted. PATH
    # contains no real curl, systemctl, runuser, su or installed daemon.
    cat > "${FIXTURE}/stubs/stub" <<'STUB'
#!/bin/bash
set -euo pipefail
command_name="${0##*/}"
printf '%s' "${command_name}" >> "${TRACE}"
printf ' <%s>' "$@" >> "${TRACE}"
printf '\n' >> "${TRACE}"
case "${command_name}" in
    getent)
        case "$*" in
            'passwd fixture-svc') exit "${ACCOUNT_MISSING}" ;;
            'group fixture-group') exit "${GROUP_MISSING}" ;;
            *) exit 91 ;;
        esac
        ;;
    id)
        case "$*" in
            '-u') printf '%s\n' "${CALLER_UID}" ;;
            '-un') printf '%s\n' "${CALLER_USER}" ;;
            '-gn') printf '%s\n' "${CALLER_GROUP}" ;;
            '-u fixture-svc') printf '%s\n' "${ACCOUNT_UID}" ;;
            *) exit 91 ;;
        esac
        ;;
    runuser)
        [[ "$1" == -u && "$2" == "${RUNUSER_NAME}" && "$3" == -g && "$4" == "${RUNUSER_GROUP}" && "$5" == -- ]]
        shift 5
        export AS_SERVICE=1
        case "$1" in
            test) [[ "${ACCESS_FAIL}" -eq 0 ]] && "$@" ;;
            "${FIXTURE}/bin/openalertd") "$@" ;;
            *) exit 91 ;;
        esac
        ;;
    su)
        [[ "$1" == -s && "$2" == /bin/sh && "$3" == openalert && "$4" == -c && "$5" == 'exec "$@"' && "$6" == sh ]]
        shift 6
        [[ "$1" == "${FIXTURE}/bin/openalertd" ]]
        export AS_SERVICE=1
        "$@"
        ;;
    install)
        [[ "$#" -eq 4 && "$1" == -m && "$2" == 0755 && "$3" == "${FIXTURE}/bin/openalertd" && "$4" == /usr/local/bin/openalertd ]]
        ;;
    openalertd)
        [[ "$#" -eq 2 && "$1" == check && "$2" == "${FIXTURE}/config/instance.toml" ]]
        printf 'check context=%s cwd=%s\n' "${AS_SERVICE}" "${PWD}" >> "${TRACE}"
        printf 'SECRET_CHECK_STDOUT\n'
        printf 'SECRET_CHECK_STDERR\n' >&2
        exit "${CHECK_EXIT}"
        ;;
    systemctl)
        case "$*" in
            'show --property=LoadState --value -- openalertd@fixture.service') printf '%s\n' "${UNIT_LOAD_STATE}" ;;
            'is-active --quiet -- openalertd@fixture.service') exit "${UNIT_ACTIVE}" ;;
            *) exit 91 ;;
        esac
        ;;
    curl)
        [[ "$1" == --disable && "$*" == *'--request GET'* && "${!#}" == 'http://127.0.0.1:18091/health?token=SECRET_URL' ]]
        printf '%s\n%s' "${HEALTH_BODY}" "${HTTP_STATUS}"
        printf 'SECRET_CURL_STDERR\n' >&2
        exit "${CURL_EXIT}"
        ;;
    *) exit 91 ;;
esac
STUB
    chmod +x "${FIXTURE}/stubs/stub"
    local command_name
    for command_name in getent id runuser systemctl curl; do
        ln -s stub "${FIXTURE}/stubs/${command_name}"
    done
    ln -s ../stubs/stub "${FIXTURE}/bin/openalertd"
    ln -s "$(command -v dirname)" "${FIXTURE}/stubs/dirname"
    ln -s "$(command -v jq)" "${FIXTURE}/stubs/jq"
    VERIFY_ARGS=(
        --config "${FIXTURE}/config/instance.toml"
        --unit openalertd@fixture.service
        --health-url 'http://127.0.0.1:18091/health?token=SECRET_URL'
        --binary "${FIXTURE}/bin/openalertd"
        --user fixture-svc --group fixture-group
        --state-dir "${FIXTURE}/state"
        --templates-dir "${FIXTURE}/templates"
        --log-dir "${FIXTURE}/logs"
    )
}

run_verify() {
    local expected_status="$1" status=0
    shift
    PATH="${FIXTURE}/stubs" /bin/bash "${PACKAGING_DIR}/verify_install.sh" \
        "${VERIFY_ARGS[@]}" "$@" > "${VERIFY_OUTPUT}" 2>&1 || status=$?
    [[ "${status}" -eq "${expected_status}" ]] || {
        printf 'Expected verifier exit %s, got %s\n' "${expected_status}" "${status}" >&2
        return 1
    }
    assert_not_contains "${VERIFY_OUTPUT}" SECRET_
}

test_named_instance_verification() {
    prepare_verify_fixture named
    run_verify 0
    assert_contains "${TRACE}" "openalertd <check> <${FIXTURE}/config/instance.toml>"
    assert_contains "${TRACE}" "check context=1 cwd=${FIXTURE}/state"
    assert_contains "${TRACE}" 'getent <passwd> <fixture-svc>'
    assert_contains "${TRACE}" 'getent <group> <fixture-group>'
    assert_contains "${TRACE}" 'systemctl <is-active> <--quiet> <--> <openalertd@fixture.service>'
    assert_contains "${TRACE}" 'curl <--disable>'
    assert_contains "${TRACE}" '<--request> <GET>'
    assert_contains "${TRACE}" '<--connect-timeout> <2> <--max-time> <5>'
    assert_contains "${TRACE}" "<test> <-w> <${FIXTURE}/logs>"
    assert_contains "${VERIFY_OUTPUT}" "Directory '${FIXTURE}/templates' exists."
    assert_contains "${VERIFY_OUTPUT}" 'HTTP health returned 200 with status ok'
    assert_contains "${VERIFY_OUTPUT}" 'Limits:'
}

test_service_account_context() {
    prepare_verify_fixture service-account
    export CALLER_UID=1001 CALLER_USER=fixture-svc CALLER_GROUP=fixture-group AS_SERVICE=1
    run_verify 0
    assert_contains "${TRACE}" 'check context=1'
    assert_not_contains "${TRACE}" 'runuser '
    assert_not_contains "${VERIFY_OUTPUT}" 'Cannot assume'
}

test_unprivileged_limitations() {
    prepare_verify_fixture unprivileged
    export CALLER_UID=1002
    run_verify 0
    assert_contains "${TRACE}" 'check context=0'
    assert_contains "${VERIFY_OUTPUT}" 'Service-account filesystem access is not verified'
    assert_not_contains "${TRACE}" 'runuser '
}

test_configuration_failure() {
    prepare_verify_fixture invalid-config
    export CHECK_EXIT=1
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" 'Configuration check FAILED'
}

test_unhealthy_responses() {
    prepare_verify_fixture unhealthy
    local body
    for body in '{"status":"failed","message":"ok"}' '{"message":"ok"}' \
        '{"nested":{"status":"ok"}}' '[]' 'not-json SECRET_BODY' \
        '{"status":"ok"} {"status":"ok"}'; do
        export HEALTH_BODY="${body}"
        run_verify 1
        assert_contains "${VERIFY_OUTPUT}" 'invalid/unhealthy JSON'
    done
    export HEALTH_BODY='{"status":"ok"}'
    for HTTP_STATUS in 204 301 401 500; do
        export HTTP_STATUS
        run_verify 1
    done
    export HTTP_STATUS=200 CURL_EXIT=28
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" 'HTTP health request failed'
}

test_unit_failures() {
    prepare_verify_fixture unit-failures
    export UNIT_LOAD_STATE=not-found
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" 'not loaded or cannot be queried'
    export UNIT_LOAD_STATE=loaded UNIT_ACTIVE=3
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" 'inactive or cannot be queried'
}

test_missing_verification_tools() {
    local command_name
    for command_name in curl jq systemctl; do
        prepare_verify_fixture "missing-${command_name}"
        rm -- "${FIXTURE}/stubs/${command_name}"
        run_verify 1
        assert_contains "${VERIFY_OUTPUT}" "${command_name} is unavailable"
    done
}

test_missing_runuser_limitations() {
    prepare_verify_fixture missing-runuser
    rm -- "${FIXTURE}/stubs/runuser"
    run_verify 0
    assert_contains "${VERIFY_OUTPUT}" 'Service-account filesystem access is not verified'
    assert_contains "${TRACE}" 'check context=0'
}

test_account_and_permission_failures() {
    prepare_verify_fixture account-permissions
    export ACCOUNT_MISSING=2
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" "System user 'fixture-svc' does not exist"
    export ACCOUNT_MISSING=0 GROUP_MISSING=2
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" "System group 'fixture-group' does not exist"
    export GROUP_MISSING=0 ACCOUNT_UID=0
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" 'Service account must not be root'
    export ACCOUNT_UID=1001 ACCESS_FAIL=1
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" 'NOT writable/searchable'
}

test_missing_paths() {
    prepare_verify_fixture missing-paths
    rmdir "${FIXTURE}/templates" "${FIXTURE}/logs"
    rm -- "${FIXTURE}/config/instance.toml" "${FIXTURE}/bin/openalertd"
    run_verify 1
    assert_contains "${VERIFY_OUTPUT}" "Directory '${FIXTURE}/templates' is missing"
    assert_contains "${VERIFY_OUTPUT}" "Directory '${FIXTURE}/logs' is missing"
    assert_contains "${VERIFY_OUTPUT}" 'missing or not executable'
    assert_contains "${VERIFY_OUTPUT}" "Configuration file '${FIXTURE}/config/instance.toml' not found"
}

test_invalid_arguments() {
    prepare_verify_fixture invalid-arguments
    run_verify 2 --unknown
    run_verify 2 --config
    run_verify 2 --group ''
    run_verify 2 --binary relative/path
    run_verify 2 --health-url file:///etc/passwd
    [[ ! -s "${TRACE}" ]]
    run_verify 0 --help
    [[ ! -s "${TRACE}" ]]
}

test_installer_validation() {
    prepare_verify_fixture installer-check
    export RED='' GREEN='' YELLOW='' BLUE='' NC=''
    export RUNUSER_NAME=openalert RUNUSER_GROUP=openalert
    awk '
        /^set -euo pipefail/ { print }
        /^log_[a-z]+\(\)/ { print }
        /^# 9\./ { selected = 1 }
        /^# 10\./ { selected = 0 }
        selected {
            gsub("/var/lib/openalertd", sprintf("%c%s/state%c", 39, ENVIRON["FIXTURE"], 39))
            gsub("/usr/local/bin/openalertd", sprintf("%c%s/bin/openalertd%c", 39, ENVIRON["FIXTURE"], 39))
            gsub("/etc/openalertd/openalertd.toml", sprintf("%c%s/config/instance.toml%c", 39, ENVIRON["FIXTURE"], 39))
            print
        }
    ' "${PACKAGING_DIR}/install.sh" > "${FIXTURE}/check.sh"
    PATH="${FIXTURE}/stubs" /bin/bash "${FIXTURE}/check.sh" > "${VERIFY_OUTPUT}" 2>&1
    assert_contains "${TRACE}" 'runuser <-u> <openalert> <-g> <openalert>'
    assert_contains "${TRACE}" "check context=1 cwd=${FIXTURE}/state"
    assert_not_contains "${VERIFY_OUTPUT}" SECRET_

    export CHECK_EXIT=1
    if PATH="${FIXTURE}/stubs" /bin/bash "${FIXTURE}/check.sh" > "${VERIFY_OUTPUT}" 2>&1; then
        return 1
    fi
    assert_contains "${VERIFY_OUTPUT}" 'Configuration dry-run failed'
    assert_not_contains "${VERIFY_OUTPUT}" SECRET_

    export CHECK_EXIT=0
    rm -- "${FIXTURE}/stubs/runuser"
    ln -s stub "${FIXTURE}/stubs/su"
    PATH="${FIXTURE}/stubs" /bin/bash "${FIXTURE}/check.sh" > "${VERIFY_OUTPUT}" 2>&1
    assert_contains "${TRACE}" 'su <-s> </bin/sh> <openalert>'
    assert_not_contains "${VERIFY_OUTPUT}" SECRET_

    rm -- "${FIXTURE}/stubs/su"
    PATH="${FIXTURE}/stubs" /bin/bash "${FIXTURE}/check.sh" > "${VERIFY_OUTPUT}" 2>&1
    assert_contains "${VERIFY_OUTPUT}" 'without verifying service-account access'
    assert_not_contains "${VERIFY_OUTPUT}" SECRET_
}

test_installer_no_file_capabilities() {
    prepare_verify_fixture installer-capabilities
    export RED='' GREEN='' YELLOW='' BLUE='' NC=''
    export BINARY_PATH="${FIXTURE}/bin/openalertd"
    ln -s stub "${FIXTURE}/stubs/install"
    ln -s stub "${FIXTURE}/stubs/setcap"
    awk '
        /^set -euo pipefail/ { print }
        /^log_[a-z]+\(\)/ { print }
        /^# 5\./ { selected = 1 }
        /^# 6\./ { selected = 0 }
        selected { print }
    ' "${PACKAGING_DIR}/install.sh" > "${FIXTURE}/binary-install.sh"
    PATH="${FIXTURE}/stubs" /bin/bash "${FIXTURE}/binary-install.sh" > "${VERIFY_OUTPUT}" 2>&1
    assert_contains "${TRACE}" 'install <-m> <0755>'
    assert_not_contains "${TRACE}" 'setcap '
}

command -v jq >/dev/null || { printf 'Tests require jq.\n' >&2; exit 1; }

run_test test_source_build_lookup
run_test test_source_template_lookup
run_test test_bundle_without_builder_helpers
run_test test_source_without_lockfile
run_test test_source_build_failure
run_test test_named_instance_verification
run_test test_service_account_context
run_test test_unprivileged_limitations
run_test test_configuration_failure
run_test test_unhealthy_responses
run_test test_unit_failures
run_test test_missing_verification_tools
run_test test_missing_runuser_limitations
run_test test_account_and_permission_failures
run_test test_missing_paths
run_test test_invalid_arguments
run_test test_installer_validation
run_test test_installer_no_file_capabilities

printf '%s passed; %s failed\n' "${PASS_COUNT}" "${FAIL_COUNT}"
[[ "${FAIL_COUNT}" -eq 0 ]]