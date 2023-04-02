# The Qubes OS Project, http://www.qubes-os.org
#
# Copyright (C) 2023 Frédéric Pierret (fepitre) <frederic@invisiblethingslab.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from datetime import datetime

from qubesbuilder.component import QubesComponent
from qubesbuilder.config import Config
from qubesbuilder.distribution import QubesDistribution
from qubesbuilder.executors import ExecutorError
from qubesbuilder.pluginmanager import PluginManager
from qubesbuilder.log import get_logger
from qubesbuilder.plugins import ArchlinuxDistributionPlugin
from qubesbuilder.plugins.publish import PublishPlugin, PublishError

log = get_logger("publish_archlinux")


class ArchlinuxPublishPlugin(ArchlinuxDistributionPlugin, PublishPlugin):
    """
    ArchlinuxPublishPlugin manages Archlinux distribution publication.

    Stages:
        - publish - Create repository to be published and uploaded to remote mirror.

    Entry points:
        - build
    """

    stages = ["publish"]
    dependencies = ["publish"]

    def __init__(
        self,
        component: QubesComponent,
        dist: QubesDistribution,
        config: Config,
        manager: PluginManager,
        **kwargs,
    ):
        super().__init__(component=component, dist=dist, config=config, manager=manager)

    def publish(self, executor, directory, keyring_dir, repository_publish):
        # directory basename will be used as prefix for some artifacts
        directory_bn = directory.mangle()

        # Build artifacts (source included)
        build_artifacts_dir = self.get_dist_component_artifacts_dir(stage="build")

        # Publish repository
        artifacts_dir = self.get_repository_publish_dir() / self.dist.type

        # Read information from build stage
        build_info = self.get_dist_artifacts_info(stage="build", basename=directory_bn)

        if not build_info.get("pkgs", None):
            log.info(f"{self.component}:{self.dist}:{directory}: Nothing to publish.")
            return

        log.info(f"{self.component}:{self.dist}:{directory}: Publishing packages.")

        packages_list = [
            build_artifacts_dir / "pkgs" / pkg for pkg in build_info["pkgs"]
        ]

        # Verify signatures (sanity check, refuse to publish if packages weren't signed)
        try:
            log.info(f"{self.component}:{self.dist}:{directory}: Verifying signatures.")
            cmd = []
            for pkg in packages_list:
                cmd += [f"gpg2 -q --homedir {keyring_dir} --verify {pkg}.sig {pkg}"]
            executor.run(cmd)
        except ExecutorError as e:
            msg = (
                f"{self.component}:{self.dist}:{directory}: Failed to check signatures."
            )
            raise PublishError(msg) from e

        # Publishing packages
        cmd = []
        try:
            target_dir = (
                artifacts_dir
                / f"{self.config.qubes_release}/{repository_publish}/{self.dist.package_set}/{self.dist.name}"
            )
            (target_dir / "pkgs").mkdir(parents=True, exist_ok=True)
            if not (target_dir / "pkgs/qubes.db").exists:
                cmd += [f"repo-add {target_dir}/pkgs/qubes.db.tar.gz"]
            for pkg in packages_list:
                target_path = target_dir / "pkgs" / pkg.name
                target_path.unlink(missing_ok=True)
                os.link(pkg, target_path)
                os.link(
                    pkg.with_suffix(".zst.sig"), target_path.with_suffix(".zst.sig")
                )
                cmd = [f"repo-add {target_dir}/pkgs/qubes.db.tar.gz {pkg}"]
            executor.run(cmd)
        except ExecutorError as e:
            msg = (
                f"{self.component}:{self.dist}:{directory}: Failed to publish packages."
            )
            raise PublishError(msg) from e

    def unpublish(self, executor, directory, repository_publish):
        # directory basename will be used as prefix for some artifacts
        directory_bn = directory.mangle()

        # Build artifacts (source included)
        build_artifacts_dir = self.get_dist_component_artifacts_dir(stage="build")

        # Publish repository
        artifacts_dir = self.get_repository_publish_dir() / self.dist.type

        # Read information from build stage
        build_info = self.get_dist_artifacts_info(stage="build", basename=directory_bn)

        if not build_info.get("pkgs", None):
            log.info(f"{self.component}:{self.dist}:{directory}: Nothing to unpublish.")
            return

        log.info(f"{self.component}:{self.dist}:{directory}: Unpublishing packages.")

        packages_list = [
            build_artifacts_dir / "pkgs" / pkg for pkg in build_info["pkgs"]
        ]

        # Unpublishing packages
        cmd = []
        try:
            target_dir = (
                artifacts_dir
                / f"{self.config.qubes_release}/{repository_publish}/{self.dist.package_set}/{self.dist.name}"
            )
            if not (target_dir / "pkgs/qubes.db").exists:
                return
            for pkg in packages_list:
                target_path = target_dir / "pkgs" / pkg.name
                target_sig_path = target_path.with_suffix(".zst.sig")

                target_path.unlink(missing_ok=True)
                target_sig_path.unlink(missing_ok=True)

                pkg_name = pkg.name.replace(
                    f"-{self.component.verrel}-{self.dist.architecture}.pkg.tar.zst", ""
                )
                cmd = [f"repo-remove {target_dir}/pkgs/qubes.db.tar.gz {pkg_name}"]
            executor.run(cmd)
        except ExecutorError as e:
            msg = (
                f"{self.component}:{self.dist}:{directory}: Failed to publish packages."
            )
            raise PublishError(msg) from e

    def run(
        self,
        stage: str,
        repository_publish: str = None,
        ignore_min_age: bool = False,
        unpublish: bool = False,
        **kwargs,
    ):
        """
        Run plugin for given stage.
        """
        # Run stage defined by parent class
        super().run(stage=stage)

        if stage != "publish" or not self.has_component_packages("publish"):
            return

        executor = self.config.get_executor_from_config(stage)
        parameters = self.get_parameters(stage)

        # Check if we have a signing key provided
        sign_key = self.config.sign_key.get(
            self.dist.distribution, None
        ) or self.config.sign_key.get("archlinux", None)
        if not sign_key:
            log.info(f"{self.component}:{self.dist}: No signing key found.")
            return

        # Check if we have a gpg client provided
        if not self.config.gpg_client:
            log.info(f"{self.component}: Please specify GPG client to use!")
            return

        # Sign artifacts
        sign_artifacts_dir = self.get_dist_component_artifacts_dir(stage="sign")

        # Keyring used for signing
        keyring_dir = sign_artifacts_dir / "keyring"

        repository_publish = repository_publish or self.config.repository_publish.get(
            "components"
        )
        if not repository_publish:
            raise PublishError("Cannot determine repository for publish")

        if not unpublish:
            if not sign_artifacts_dir.exists():
                raise PublishError("Cannot find keyring from sign stage.")

            # Check if publish repository is valid
            self.validate_repository_publish(repository_publish)

            # Check if we already published packages into the provided repository
            if all(
                self.is_published(
                    basename=directory.mangle(),
                    repository=repository_publish,
                )
                for directory in parameters["build"]
            ):
                log.info(
                    f"{self.component}:{self.dist}: Already published to '{repository_publish}'."
                )
                return

            # Check if we can publish into current
            if repository_publish == "current" and not all(
                self.can_be_published_in_stable(
                    basename=directory.mangle(),
                    ignore_min_age=ignore_min_age,
                )
                for directory in parameters["build"]
            ):
                failure_msg = (
                    f"{self.component}:{self.dist}: "
                    f"Refusing to publish to 'current' as packages are not "
                    f"uploaded to 'current-testing' or 'security-testing' "
                    f"for at least {self.config.min_age_days} days."
                )
                raise PublishError(failure_msg)

            for directory in parameters["build"]:
                # directory basename will be used as prefix for some artifacts
                directory_bn = directory.mangle()

                build_info = self.get_dist_artifacts_info(
                    stage="build", basename=directory_bn
                )
                publish_info = self.get_dist_artifacts_info(
                    stage=stage, basename=directory_bn
                )

                if not build_info:
                    raise PublishError(
                        f"{self.component}:{self.dist}:{directory}: Cannot find build info."
                    )

                # If previous publication to a repo has been done and does not correspond to current
                # build artifacts, we delete previous publications. It happens if we modify local
                # sources and then publish into repository with the same version and release.
                info = build_info
                if publish_info:
                    if build_info["source-hash"] != publish_info["source-hash"]:
                        log.info(
                            f"{self.component}:{self.dist}:{directory}: Current build hash does not match previous one."
                        )
                        for repository in publish_info.get("repository-publish", []):
                            self.unpublish(
                                executor=executor,
                                directory=directory,
                                repository_publish=repository,
                            )
                    else:
                        info = publish_info

                self.publish(
                    executor=executor,
                    directory=directory,
                    keyring_dir=keyring_dir,
                    repository_publish=repository_publish,
                )

                # Save package information we published for committing into current
                info.setdefault("repository-publish", []).append(
                    {
                        "name": repository_publish,
                        "timestamp": datetime.utcnow().strftime("%Y%m%d%H%M"),
                    }
                )
                self.save_dist_artifacts_info(
                    stage="publish", basename=directory_bn, info=info
                )

        if unpublish:
            if not all(
                self.is_published(
                    basename=directory.mangle(),
                    repository=repository_publish,
                )
                for directory in parameters["build"]
            ):
                log.info(
                    f"{self.component}:{self.dist}: Not published to '{repository_publish}'."
                )
                return

            for directory in parameters["build"]:
                # directory basename will be used as prefix for some artifacts
                directory_bn = directory.mangle()

                publish_info = self.get_dist_artifacts_info(
                    stage=stage, basename=directory_bn
                )

                self.unpublish(
                    executor=executor,
                    directory=directory,
                    repository_publish=repository_publish,
                )

                # Save package information we published for committing into current. If the packages
                # are not published into another repository, we delete the publish stage information.
                publish_info["repository-publish"] = [
                    r
                    for r in publish_info.get("repository-publish", [])
                    if r["name"] != repository_publish
                ]
                if publish_info.get("repository-publish", []):
                    self.save_dist_artifacts_info(
                        stage="publish", basename=directory_bn, info=publish_info
                    )
                else:
                    log.info(
                        f"{self.component}:{self.dist}:{directory}: Not published anywhere else, deleting publish info."
                    )
                    self.delete_dist_artifacts_info(
                        stage="publish", basename=directory_bn
                    )


PLUGINS = [ArchlinuxPublishPlugin]
