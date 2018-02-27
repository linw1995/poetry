from typing import List

from poetry.packages import Locker
from poetry.packages import Package
from poetry.puzzle import Solver
from poetry.puzzle.operations import Install
from poetry.puzzle.operations import Uninstall
from poetry.puzzle.operations import Update
from poetry.puzzle.operations.operation import Operation
from poetry.repositories import Repository
from poetry.repositories.installed_repository import InstalledRepository

from .pip_installer import PipInstaller


class Installer:

    def __init__(self,
                 io,
                 package: Package,
                 locker: Locker,
                 repository: Repository):
        self._io = io
        self._package = package
        self._locker = locker
        self._repository = repository

        self._dry_run = False
        self._update = False
        self._verbose = False
        self._write_lock = True
        self._dev_mode = True
        self._execute_operations = True

        self._installer = PipInstaller(self._io.venv, self._io)

    def run(self):
        # Force update if there is no lock file present
        if not self._update and not self._locker.is_locked():
            self._update = True

        if self.is_dry_run():
            self.verbose(True)
            self._write_lock = False
            self._execute_operations = False

        local_repo = Repository()
        self._do_install(local_repo)

        if self._update and self._write_lock:
            updated_lock = self._locker.set_lock_data(
                self._package,
                local_repo.packages
            )

            if updated_lock:
                self._io.writeln('<info>Writing lock file</>')

        return 0

    def dry_run(self, dry_run=True) -> 'Installer':
        self._dry_run = dry_run

        return self

    def is_dry_run(self) -> bool:
        return self._dry_run

    def verbose(self, verbose=True) -> 'Installer':
        self._verbose = verbose

        return self

    def is_verbose(self) -> bool:
        return self._verbose

    def dev_mode(self, dev_mode=True) -> 'Installer':
        self._dev_mode = dev_mode

        return self

    def is_dev_mode(self) -> bool:
        return self._dev_mode

    def update(self, update=True) -> 'Installer':
        self._update = update

        return self

    def is_updating(self) -> bool:
        return self._update

    def execute_operations(self, execute=True) -> 'Installer':
        self._execute_operations = execute

        return self

    def _do_install(self, local_repo):
        locked_repository = Repository()
        # initialize locked repo if we are installing from lock
        if not self._update:
            locked_repository = self._locker.locked_repository(self._dev_mode)

        solver = Solver(locked_repository, self._io)

        request = self._package.requires
        if self.is_dev_mode():
            request += self._package.dev_requires

        if self._update:
            self._io.writeln('<info>Updating dependencies</>')

            ops = solver.solve(request, self._repository)
        else:
            self._io.writeln('<info>Installing dependencies from lock file</>')
            # If we are installing from lock
            # Filter the operations by comparing it with what is
            # currently installed
            ops = self._get_operations_from_lock(locked_repository)

        self._io.new_line()

        # Execute operations
        if not ops:
            self._io.writeln('Nothing to install or update')

        # extract dev packages and mark them to be skipped
        # if it's a --no-dev install or update
        # we also force them to be uninstalled
        # if they are present in the local repo
        # TODO

        if ops and self._execute_operations:
            installs = []
            updates = []
            uninstalls = []
            for op in ops:
                if op.job_type == 'install':
                    installs.append(
                        f'{op.package.pretty_name}'
                        f':{op.package.full_pretty_version}'
                    )
                elif op.job_type == 'update':
                    updates.append(
                        f'{op.target_package.pretty_name}'
                        f':{op.target_package.full_pretty_version}'
                    )
                elif op.job_type == 'uninstall':
                    uninstalls.append(
                        f'{op.package.pretty_name}'
                    )

            self._io.new_line()
            self._io.writeln(
                'Package operations: '
                f'<info>{len(installs)}</> install{"" if len(installs) == 1 else "s"}, '
                f'<info>{len(updates)}</> update{"" if len(updates) == 1 else "s"}, '
                f'<info>{len(uninstalls)}</> removal{"" if len(uninstalls) == 1 else "s"}'
                f''
            )
            self._io.new_line()

        for op in ops:
            if op.job_type == 'install':
                local_repo.add_package(op.package)
            elif op.job_type == 'update':
                local_repo.add_package(op.target_package)

            if self._execute_operations:
                self._execute(op)

    def _execute(self, operation: Operation) -> None:
        """
        Execute a given operation.
        """
        method = operation.job_type

        getattr(self, f'_execute_{method}')(operation)

    def _execute_install(self, operation: Install) -> None:
        self._installer.install(operation.package)

    def _execute_update(self, operation: Update) -> None:
        self._installer.update(
            operation.initial_package,
            operation.target_package
        )

    def _execute_uninstall(self, operation: Uninstall) -> None:
        self._installer.remove(operation.package)

    def _get_operations_from_lock(self,
                                  locked_repository: Repository
                                  ) -> List[Operation]:
        installed_repo = InstalledRepository.load(self._io.venv)
        ops = []

        for locked in locked_repository.packages:
            is_installed = False
            for installed in installed_repo.packages:
                if locked.name == installed.name:
                    is_installed = True
                    if locked.version != installed.version:
                        ops.append(Update(
                            installed, locked
                        ))

            if not is_installed:
                ops.append(Install(locked))

        return ops


