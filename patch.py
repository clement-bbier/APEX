import sys

with open('supervisor/orchestrator.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace(
    'self._started: list[str] = []',
    'self._started: list[str] = []\n        self._processes: dict[str, asyncio.subprocess.Process] = {}'
)

old_startup = '''            logger.info("Starting service", service=service_id)
            # Phase 2: actually spawn subprocess here
            # For now, log the intent
            healthy = await self.health_gate(service_id, timeout_s=30.0)'''

new_startup = '''            logger.info("Starting service", service=service_id)

            python_exe = sys.executable
            # Ensure we use .venv/Scripts/python if available
            cmd = [python_exe, "-m", f"services.{service_id}.service"]

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            self._processes[service_id] = process

            async def log_output(proc, name):
                if proc.stdout is None:
                    return
                for _ in range(10):
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    print(f"[{name}] {line.decode('utf-8', errors='ignore').rstrip()}")
            
            asyncio.create_task(log_output(process, service_id))

            healthy = await self.health_gate(service_id, timeout_s=30.0)'''

text = text.replace(old_startup, new_startup)

old_shutdown = '''    async def shutdown(self) -> None:
        """Shutdown services in reverse startup order."""
        logger.info("Shutting down APEX Trading System")
        for service_id in reversed(self._started):
            logger.info("Stopping service", service=service_id)
            # Phase 2: send SIGTERM to subprocess
        self._started.clear()'''

new_shutdown = '''    async def shutdown(self) -> None:
        """Shutdown services in reverse startup order."""
        logger.info("Shutting down APEX Trading System")
        for service_id in reversed(self._started):
            logger.info("Stopping service", service=service_id)
            process = self._processes.get(service_id)
            if process:
                try:
                    process.terminate()
                except ProcessLookupError:
                    pass
        self._started.clear()
        self._processes.clear()'''

text = text.replace(old_shutdown, new_shutdown)

with open('supervisor/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(text)
print('Orchestrator updated')
