cd ~/user-preferences-service

cat > deploy.sh << 'EOF'
#!/usr/bin/env bash
set -e

cd infra
cdk deploy --require-approval never
EOF
