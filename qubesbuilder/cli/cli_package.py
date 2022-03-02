import click

from qubesbuilder.config import STAGES, STAGES_ALIAS
from qubesbuilder.cli.cli_base import aliased_group, ContextObj
from qubesbuilder.plugins.helpers import (
    getSourcePlugin,
    getBuildPlugin,
    getSignPlugin,
    getPublishPlugin,
)


@aliased_group("package", chain=True)
def package():
    """
    Package CLI
    """


# FIXME: Find a better design to register necessary plugins for each stage.
def _component_stage(obj: ContextObj, stage_name: str):
    """
    Generic function to trigger stage for a standard component
    """
    click.echo(f"Running stage: {stage_name}")
    executor = obj.config.get_stages()[stage_name]["executor"]

    for component in obj.components:
        for dist in obj.distributions:
            plugins = [
                getSourcePlugin(
                    component=component,
                    dist=dist,
                    plugins_dir=obj.config.get_plugins_dir(),
                    executor=executor,
                    artifacts_dir=obj.config.get_artifacts_dir(),
                    verbose=obj.config.verbose,
                    debug=obj.config.debug,
                    skip_if_exists=obj.config.get("reuse-fetched-source"),
                ),
                getBuildPlugin(
                    component=component,
                    dist=dist,
                    plugins_dir=obj.config.get_plugins_dir(),
                    executor=executor,
                    artifacts_dir=obj.config.get_artifacts_dir(),
                    verbose=obj.config.verbose,
                    debug=obj.config.debug,
                    use_qubes_repo=obj.config.get("use-qubes-repo"),
                ),
                getSignPlugin(
                    component=component,
                    dist=dist,
                    plugins_dir=obj.config.get_plugins_dir(),
                    executor=executor,
                    artifacts_dir=obj.config.get_artifacts_dir(),
                    verbose=obj.config.verbose,
                    debug=obj.config.debug,
                    gpg_client=obj.config.get("gpg-client"),
                    sign_key=obj.config.get("sign-key"),
                ),
                getPublishPlugin(
                    component=component,
                    dist=dist,
                    plugins_dir=obj.config.get_plugins_dir(),
                    executor=executor,
                    artifacts_dir=obj.config.get_artifacts_dir(),
                    verbose=obj.config.verbose,
                    debug=obj.config.debug,
                    gpg_client=obj.config.get("gpg-client"),
                    sign_key=obj.config.get("sign-key"),
                    qubes_release=obj.config.get("qubes-release"),
                    publish_repository=obj.config.get("publish-repository"),
                ),
            ]
            for plugin in plugins:
                plugin.run(stage=stage_name)


@click.command(name="all", short_help="Run all package stages.")
@click.pass_obj
def _all_package_stage(obj: ContextObj):
    for s in STAGES:
        _component_stage(obj=obj, stage_name=s)


@package.command()
@click.pass_obj
def fetch(obj: ContextObj):
    _component_stage(obj=obj, stage_name="fetch")


@package.command()
@click.pass_obj
def prep(obj: ContextObj):
    _component_stage(obj=obj, stage_name="prep")


@package.command()
@click.pass_obj
def build(obj: ContextObj):
    _component_stage(obj=obj, stage_name="build")


@package.command()
@click.pass_obj
def post(obj: ContextObj):
    _component_stage(obj=obj, stage_name="post")


@package.command()
@click.pass_obj
def verify(obj: ContextObj):
    _component_stage(obj=obj, stage_name="verify")


@package.command()
@click.pass_obj
def sign(obj: ContextObj):
    _component_stage(obj=obj, stage_name="sign")


@package.command()
@click.pass_obj
def publish(obj: ContextObj):
    _component_stage(obj=obj, stage_name="publish")


package.add_command(fetch)
package.add_command(prep)
package.add_command(build)
package.add_command(post)
package.add_command(verify)
package.add_command(sign)
package.add_command(publish)
package.add_command(_all_package_stage)

package.add_alias(**STAGES_ALIAS)
