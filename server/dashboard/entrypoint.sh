#!/bin/sh
set -e

cd /app

# Swap NEXT_PUBLIC_* placeholders baked into .next/ at build time with the
# container's real env values. Each placeholder must be declared in the
# Dockerfile as `ENV NAME=NAME` so Next.js inlines the literal name. Currently:
#   NEXT_PUBLIC_API_URL, NEXT_PUBLIC_INSTANCE_NAME
# New NEXT_PUBLIC_* vars must be added to the Dockerfile or this loop won't substitute them.
#
# Deliberately NOT substituted: NEXT_PUBLIC_APP_VERSION / _GIT_SHA / _BUILT_AT.
# Those are declared as `ENV NAME=${BUILD_ARG}` so Next inlines their real value
# at build time. They identify the commit the bundle was compiled from, so
# rewriting them at container start would defeat the point - the badge would
# report the deploy's env instead of the build's provenance.
printenv | grep '^NEXT_PUBLIC_' | while IFS='=' read -r key value; do
  escaped=$(printf '%s' "$value" | sed -e 's/[\\&|]/\\&/g')
  find .next/ -type f -exec sed -i "s|$key|$escaped|g" {} \;
done
echo "Done replacing env variables NEXT_PUBLIC_ with real values"

exec "$@"
