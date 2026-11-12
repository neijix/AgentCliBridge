# Installer packages (README › Install). The gate itself is ./check.sh, not make.
.PHONY: check package release sums

check:
	./check.sh

# This OS's installer package into dist/ (.deb, .pkg or .exe), built from one snapshot archive of
# HEAD, or of TAG=vX.Y.Z. REPO=OWNER/REPO names the GitHub repo when origin is not github.com.
package:
	bash packaging/release.sh package $(if $(TAG),--tag $(TAG)) $(if $(REPO),--repo $(REPO))

# package, then upload it to the GitHub Release of the v* tag at HEAD (or TAG=) with SHA256SUMS
# rewritten. A package already attached is refused unless CLOBBER=1.
release:
	bash packaging/release.sh release $(if $(TAG),--tag $(TAG)) $(if $(REPO),--repo $(REPO)) $(if $(filter 1,$(CLOBBER)),--clobber)

# Only rewrite SHA256SUMS on the tag's existing Release.
sums:
	bash packaging/release.sh sums $(if $(TAG),--tag $(TAG)) $(if $(REPO),--repo $(REPO))
