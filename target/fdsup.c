/* fdsup.c — Flight-Deck on-target supervisor.
 *
 * Usage: fdsup <timeout_seconds> <program> [args...]
 *
 * Spawns the program as a child, inheriting the console, and waits for
 * it with a deadline. Reports exactly how the child ended, in
 * machine-readable lines the host harness harvests:
 *
 *   FDSUP start child=<prog> timeout=<n>
 *   FDSUP end   child=<prog> how=exit code=0
 *   FDCRASH     child=<prog> signal=11 signame=SIGSEGV
 *   FDCRASH     child=<prog> signal=TIMEOUT after=<n>s
 *
 * Rationale: on a minimal QNX image a process that dies from a signal
 * leaves NO trace on the console — the boot script simply continues.
 * fdsup is the missing flight recorder at process level; the host
 * harness's VM-level watchdog covers target-wide hangs above it.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <signal.h>
#include <spawn.h>
#include <sys/wait.h>

extern char **environ;

static const char *signame(int sig) {
    switch (sig) {
        case SIGABRT: return "SIGABRT";
        case SIGBUS:  return "SIGBUS";
        case SIGFPE:  return "SIGFPE";
        case SIGILL:  return "SIGILL";
        case SIGKILL: return "SIGKILL";
        case SIGSEGV: return "SIGSEGV";
        case SIGTERM: return "SIGTERM";
        case SIGTRAP: return "SIGTRAP";
        default:      return "SIG?";
    }
}

static double now_s(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 3) {
        printf("FDCRASH child=? signal=USAGE\n");
        return 2;
    }
    int timeout = atoi(argv[1]);
    const char *prog = argv[2];
    printf("FDSUP start child=%s timeout=%d\n", prog, timeout);

    pid_t pid;
    int rc = posix_spawn(&pid, prog, NULL, NULL, &argv[2], environ);
    if (rc != 0) {
        printf("FDCRASH child=%s signal=SPAWNFAIL err=%d\n", prog, rc);
        return 2;
    }

    double t0 = now_s();
    int status = 0;
    for (;;) {
        pid_t w = waitpid(pid, &status, WNOHANG);
        if (w == pid) break;
        if (w == -1 && errno != EINTR) {
            printf("FDCRASH child=%s signal=WAITFAIL err=%d\n", prog, errno);
            return 2;
        }
        if (timeout > 0 && now_s() - t0 > timeout) {
            kill(pid, SIGKILL);
            waitpid(pid, &status, 0);
            printf("FDCRASH child=%s signal=TIMEOUT after=%ds\n", prog, timeout);
            return 1;
        }
        struct timespec ts = { 0, 50 * 1000 * 1000L };
        nanosleep(&ts, NULL);
    }

    if (WIFSIGNALED(status)) {
        int sig = WTERMSIG(status);
        printf("FDCRASH child=%s signal=%d signame=%s\n", prog, sig, signame(sig));
        return 1;
    }
    int code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    printf("FDSUP end child=%s how=exit code=%d\n", prog, code);
    return code;
}
