#!/bin/bash
# CriacBot — full Oracle Cloud provisioning via OCI CLI
#
# Run this in OCI Cloud Shell (Oracle Console top-right ">_" icon).
# It creates all networking, firewall rules, and the ARM instance,
# trying each availability domain automatically until one has capacity.
#
# Usage:
#   bash oracle_provision.sh
#
# If all ADs are at capacity it exits cleanly — the networking is saved.
# Run again later with:  bash oracle_provision.sh --instance-only
set -euo pipefail

COMPARTMENT="$OCI_TENANCY"
SHAPE="VM.Standard.A1.Flex"
OCPUS=2
MEMORY_GB=12
NAME="criacbot"
UBUNTU_VERSION="22.04"

INSTANCE_ONLY="${1:-}"

# ── helpers ──────────────────────────────────────────────────────────────────

log()  { echo "==> $*"; }
info() { echo "    $*"; }
ok()   { echo "    OK: $*"; }

get_ids() {
  # Query OCI CLI output for a list of values
  python3 -c "import sys,json; [print(x) for x in json.load(sys.stdin)]"
}

get_id() {
  python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])"
}

# ── SSH key ───────────────────────────────────────────────────────────────────

log "SSH key"
if [ ! -f ~/.ssh/id_rsa ]; then
  ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -q
  info "Generated new key at ~/.ssh/id_rsa"
else
  info "Using existing key at ~/.ssh/id_rsa"
fi
SSH_KEY=$(cat ~/.ssh/id_rsa.pub)
SSH_KEY_FILE=$(mktemp)
echo "$SSH_KEY" > "$SSH_KEY_FILE"
trap "rm -f $SSH_KEY_FILE" EXIT

# ── networking (skip if --instance-only) ─────────────────────────────────────

if [ "$INSTANCE_ONLY" != "--instance-only" ]; then

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

  # Save IDs so --instance-only can reuse them
  cat > ~/.criacbot_ids << EOF
VCN_ID=$VCN_ID
SUBNET_ID=$SUBNET_ID
EOF
  info "Networking IDs saved to ~/.criacbot_ids"

else
  # Restore from previous run
  if [ ! -f ~/.criacbot_ids ]; then
    echo "ERROR: ~/.criacbot_ids not found. Run without --instance-only first."
    exit 1
  fi
  source ~/.criacbot_ids
  log "Reusing existing networking"
  info "Subnet: $SUBNET_ID"
fi

# ── find Ubuntu ARM image ─────────────────────────────────────────────────────

log "Finding latest Ubuntu ${UBUNTU_VERSION} ARM image"
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
PUBLIC_IP=""

for AD in "${ADS[@]}"; do
  info "Trying $AD ..."

  set +e
  OUTPUT=$(oci compute instance launch \
    --availability-domain "$AD" \
    --compartment-id "$COMPARTMENT" \
    --shape "$SHAPE" \
    --shape-config "{\"ocpus\":$OCPUS,\"memoryInGBs\":$MEMORY_GB}" \
    --image-id "$IMAGE_ID" \
    --subnet-id "$SUBNET_ID" \
    --assign-public-ip true \
    --ssh-authorized-keys-file "$SSH_KEY_FILE" \
    --display-name "$NAME" \
    2>&1)
  EXIT=$?
  set -e

  if [ $EXIT -eq 0 ]; then
    INSTANCE_ID=$(echo "$OUTPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['id'])")
    info "Created in $AD"
    break
  else
    info "No capacity in $AD — trying next"
  fi
done

if [ -z "$INSTANCE_ID" ]; then
  echo ""
  echo "========================================"
  echo "  All ADs at capacity right now."
  echo "  Networking is saved. Try again later:"
  echo "  bash oracle_provision.sh --instance-only"
  echo "========================================"
  exit 1
fi

# ── wait for RUNNING ──────────────────────────────────────────────────────────

log "Waiting for instance to reach RUNNING state (~2 mins)"
oci compute instance get \
  --instance-id "$INSTANCE_ID" \
  --wait-for-state RUNNING \
  --max-wait-seconds 300 > /dev/null

log "Getting public IP"
PUBLIC_IP=$(oci compute instance list-vnics \
  --instance-id "$INSTANCE_ID" \
  --query 'data[0]."public-ip"' --raw-output)

# ── done ─────────────────────────────────────────────────────────────────────

echo ""
echo "========================================"
echo "  Instance ready!"
echo "========================================"
echo ""
echo "  SSH in:"
echo "    ssh -i ~/.ssh/id_rsa ubuntu@$PUBLIC_IP"
echo ""
echo "  Save your private key locally (run on YOUR machine):"
echo "    # In Cloud Shell, print it:"
echo "    cat ~/.ssh/id_rsa"
echo "    # Copy the output and save as criacbot.pem on your machine"
echo ""
echo "  Next step: copy secrets and run setup"
echo "    (see README / setup instructions)"
echo ""

# Save public IP for reference
echo "PUBLIC_IP=$PUBLIC_IP" >> ~/.criacbot_ids
echo "INSTANCE_ID=$INSTANCE_ID" >> ~/.criacbot_ids
