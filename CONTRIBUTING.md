# Contributing to HLauncher

Bug reports, hardware compatibility results, documentation fixes, and code
changes are welcome. To make an app for your own setup or distribute it
independently, start with the [plugin authoring guide](docs/plugins.md#author-and-package-a-plugin).
It includes a [prompt for AI coding agents](docs/plugins.md#build-a-plugin-with-an-ai-agent).

## Report hardware compatibility

Open a [Hardware compatibility report](https://github.com/evy0311/HLauncher/issues/new?template=compatibility.yml)
on GitHub for a working, partly working, or unsuccessful setup. Include your
car's make, model, and year, the radio, the board model and specs, the OS, and
the HLauncher version. Describe which features and plugins you tested and any
workarounds. If you retest the same setup, comment on your report with the new
HLauncher version and results so readers can follow what changed.

## Report a bug or propose a change

Search the [issue tracker](https://github.com/evy0311/HLauncher/issues) for an
existing report. For a bug, include the HLauncher release or commit, any affected
plugin and its version, your radio and Pi models, and relevant peripherals.
Give the steps to reproduce, what you expected, and what happened. If you include
logs or screenshots, remove passwords, Bluetooth addresses, and personal data.
For a feature, describe the use case and the hardware involved.

## Make a change

1. Fork HLauncher and clone your fork. Start a feature branch from `develop`.

   ```bash
   git remote add upstream https://github.com/evy0311/HLauncher.git
   git fetch upstream develop
   git switch -c my-change upstream/develop
   ```

2. Keep the change focused. See [development and checks](docs/development.md)
   and [source setup](docs/setup.md) for the relevant components and Pi setup.
   If you reuse third-party code or assets, include the required license and
   attribution. See [LICENSE](LICENSE), [NOTICE](NOTICE), and
   [third-party notices](THIRD_PARTY_NOTICES.md).
3. Run `bash scripts/test.sh` for code changes. The script uses Python 3 and Node.
   For plugin changes, also validate the source and package and preview the
   first frame if the plugin draws one. Test hardware-facing changes while
   parked and record the hardware you used.
4. Push your feature branch to your fork and open a pull request against
   HLauncher's `develop` branch. Explain what changed, link any related issue,
   and list the checks you ran and any hardware behavior still to verify.

For changes that affect installation or persistent state, preserve the upgrade
and rollback paths described in the [update guide](docs/updates.md).
