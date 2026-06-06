#!/bin/bash
# CriacBot — full Oracle Cloud provisioning via OCI CLI
#
# Run this in OCI Cloud Shell (Oracle Console top-right ">_" icon).
#
# Usage:
#   bash oracle_provision.sh           # ARM A1.Flex (fast, 12GB) — may hit capacity
#   bash oracle_provision.sh --amd     # AMD E2.1.Micro (1GB, always available)
#   bash oracle_provision.sh --instance-only        # retry instance, reuse networking
#   bash oracle_provision.sh --amd --instance-only  # AMD retry only
set -euo pipefail

COMPARTMENT="$OCI_TENANCY"
NAME="criacbot"
UBUNTU_VERSION="22.04"

# ── parse flags ───────────────────────────────────────────────────────────────

USE_AMD=false
INSTANCE_ONLY=false
for arg in "$@"; do
  case $arg in
    --amd)           USE_AMD=true ;;
    --instance-only) INSTANCE_ONLY=true ;;
  esac
done

if $USE_AMD; then
  SHAPE="VM.Standard.E2.1.Micro"
  SHAPE_CONFIG=""   # fixed shape, no config needed
  echo "==> Using AMD E2.1.Micro (always-free, guaranteed capacity)"
else
  SHAPE="VM.Standard.A1.Flex"
  SHAPE_CONFIG='{"ocpus":2,"memoryInGBs":12}'
  echo "==> Using ARM A1.Flex (2 OCPU / 12 GB)"
fi

# ── helpers ───────────────────────────────────────────────────────────────────

log()  { echo "==> $*"; }
info() { echo "    $*"; }
ok()   { echo "    OK: $*"; }

get_ids() { python3 -c "import sys,json; [print(x) for x in json.load(sys.stdin)]"; }

# ── SSH key ───────────────────────────────────────────────────────────────────

log "SSH key"
if [ ! -f ~/.ssh/id_rsa ]; then
  ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -q
  info "Generated new key at ~/.ssh/id_rsa"
else
  info "Using existing key at ~/.ssh/id_rsa"
fi
SSH_KEY_FILE=$(mktemp)
cat ~/.ssh/id_rsa.pub > "$SSH_KEY_FILE"
trap "rm -f $SSH_KEY_FILE" EXIT

# ── networking (skip if --instance-only) ─────────────────────────────────────

if ! $INSTANCE_ONLY; then

  log "Creating VCN"
  VCN_ID=$(oci network vcn create \
    --compartment-id "$COMPARTMENT" \
    --display-name "${NAME}-vcn" \
    --cidr-block "10.0.0.0/16" \
    --wait-for-state AVAILABLE \
    --query 'data.id' --raw-output 2>/dev/null)
  ok "$VCN_ID"

  log "Creating Internet Gateway"
  IGW_ID=$(oci network internet-gateway create \
    --compartment-id "$COMPARTMENT" \
    --vcn-id "$VCN_ID" \
    --display-name "${NAME}-igw" \
    --is-enabled true \
    --wait-for-state AVAILABLE \
    --query 'data.id' --raw-output 2>/dev/null)
  ok "$IGW_ID"

  log "Updating default route table → internet"
  RT_ID=$(oci network vcn get \
    --vcn-id "$VCN_ID" \
    --query 'data."default-route-table-id"' --raw-output)
  oci network route-table update \
    --rt-id "$RT_ID" \
    --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW_ID\"}]" \
    --force \
    --wait-for-state AVAILABLE > /dev/null
  ok "route table updated"

  log "Creating Security List (SSH in, all out)"
  SL_ID=$(oci network security-list create \
    --compartment-id "$COMPARTMENT" \
    --vcn-id "$VCN_ID" \
    --display-name "${NAME}-sl" \
    --ingress-security-rules '[{"source":"0.0.0.0/0","protocol":"6","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]' \
    --egress-security-rules  '[{"destination":"0.0.0.0/0","protocol":"all","isStateless":false}]' \
    --wait-for-state AVAILABLE \
    --query 'data.id' --raw-output 2>/dev/null)
  ok "$SL_ID"

  log "Creating public subnet"
  SUBNET_ID=$(oci network subnet create \
    --compartment-id "$COMPARTMENT" \
    --vcn-id "$VCN_ID" \
    --display-name "${NAME}-subnet" \
    --cidr-block "10.0.0.0/24" \
    --route-table-id "$RT_ID" \
    --security-list-ids "[\"$SL_ID\"]" \
    --wait-for-state AVAILABLE \
    --query 'data.id' --raw-output 2>/dev/null)
  ok "$SUBNET_ID"

  printf "VCN_ID=%s\nSUBNET_ID=%s\n" "$VCN_ID" "$SUBNET_ID" > ~/.criacbot_ids
  info "Networking IDs saved to ~/.criacbot_ids"

else
  [ -f ~/.criacbot_ids ] || { echo "ERROR: ~/.criacbot_ids not found — run without --instance-only first"; exit 1; }
  source ~/.criacbot_ids
  log "Reusing existing networking"
  info "Subnet: $SUBNET_ID"
fi

# ── find Ubuntu image for chosen shape ───────────────────────────────────────

log "Finding latest Ubuntu ${UBUNTU_VERSION} image for $SHAPE"
IMAGE_ID=$(oci compute image list \
  --compartment-id "$COMPARTMENT" \
  --operating-system "Canonical Ubuntu" \
  --operating-system-version "$UBUNTU_VERSION" \
  --shape "$SHAPE" \
  --sort-by TIMECREATED \
  --sort-order DESC \
  --limit 1 \
  --query 'data[0].id' --raw-output)
ok "$IMAGE_ID"

# ── instance — try each AD ────────────────────────────────────────────────────

log "Fetching availability domains"
mapfile -t ADS < <(oci iam availability-domain list \
  --compartment-id "$COMPARTMENT" \
  --query 'data[*].name' | get_ids)

INSTANCE_ID=""

for AD in "${ADS[@]}"; do
  info "Trying $AD ..."

  LAUNCH_ARGS=(
    --availability-domain "$AD"
    --compartment-id "$COMPARTMENT"
    --shape "$SHAPE"
    --image-id "$IMAGE_ID"
    --subnet-id "$SUBNET_ID"
    --assign-public-ip true
    --ssh-authorized-keys-file "$SSH_KEY_FILE"
    --display-name "$NAME"
  )
  [ -n "$SHAPE_CONFIG" ] && LAUNCH_ARGS+=(--shape-config "$SHAPE_CONFIG")

  set +e
  OUTPUT=$(oci compute instance launch "${LAUNCH_ARGS[@]}" 2>&1)
  EXIT=$?
  set -e

  if [ $EXIT -eq 0 ]; then
    INSTANCE_ID=$(echo "$OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])")
    info "Created in $AD!"
    break
  else
    info "No capacity in $AD — trying next"
  fi
done

if [ -z "$INSTANCE_ID" ]; then
  echo ""
  echo "========================================"
  echo "  All ADs at capacity."
  echo "  Networking is saved. Retry with:"
  echo "  bash oracle_provision.sh --instance-only"
  echo "  bash oracle_provision.sh --amd --instance-only"
  echo "========================================"
  exit 1
fi

# ── wait for RUNNING ──────────────────────────────────────────────────────────

log "Waiting for instance to start (~2 mins)"
oci compute instance get \
  --instance-id "$INSTANCE_ID" \
  --wait-for-state RUNNING \
  --max-wait-seconds 300 > /dev/null

log "Getting public IP"
PUBLIC_IP=$(oci compute instance list-vnics \
  --instance-id "$INSTANCE_ID" \
  --query 'data[0]."public-ip"' --raw-output)

printf "PUBLIC_IP=%s\nINSTANCE_ID=%s\n" "$PUBLIC_IP" "$INSTANCE_ID" >> ~/.criacbot_ids

# ── done ─────────────────────────────────────────────────────────────────────

echo ""
echo "========================================"
echo "  Instance ready!"
echo "========================================"
echo ""
echo "  SSH in:"
echo "    ssh -i ~/.ssh/id_rsa ubuntu@$PUBLIC_IP"
echo ""
echo "  Run setup on the server:"
echo "    ssh ubuntu@$PUBLIC_IP 'bash <(curl -fsSL https://raw.githubusercontent.com/DRourke-87/Criac/main/scripts/setup.sh)'"
echo ""
echo "  IMPORTANT — save your private key to your local machine:"
echo "    cat ~/.ssh/id_rsa"
echo "    (copy the output and save it as criacbot.pem)"
echo ""
