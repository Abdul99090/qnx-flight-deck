/* fdwatch.c — watchdog demo target for QNX Flight-Deck.
 *
 * Emits a heartbeat line every 500 ms. Two build flavours:
 *
 *   healthy : qcc -o fdwatch fdwatch.c
 *             -> 6 heartbeats, then a one-line FDTEST suite result
 *                and FDTEST DONE; the harness verdict is PASS.
 *
 *   hanging : qcc -DFD_HANG_AFTER=3 -o fdwatch fdwatch.c
 *             -> 3 heartbeats, then the main thread wedges in a
 *                priority-raised busy loop: no more console output.
 *                A Flight-Deck run with --watchdog must detect the
 *                silence, restart the VM, and record the events.
 */
#include <stdio.h>
#include <unistd.h>
#include <sched.h>
#include <sys/neutrino.h>

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("FDTEST START sysname=QNX\n");
    fflush(stdout);
    int beat = 0;
    for (;;) {
        beat++;
        printf("FDHEARTBEAT %d\n", beat);
        fflush(stdout);
#ifdef FD_HANG_AFTER
        if (beat >= FD_HANG_AFTER) {
            /* Wedge: raise our priority and spin forever without
             * yielding — the classic runaway real-time thread. */
            struct sched_param sp;
            sp.sched_priority = 200;
            ThreadCtl(_NTO_TCTL_RUNMASK, NULL); /* no-op sanity call */
            sched_setscheduler(0, SCHED_FIFO, &sp);
            for (;;) { }
        }
#endif
        if (beat >= 6) break;
        struct timespec ts = { 0, 500 * 1000 * 1000L };
        nanosleep(&ts, NULL);
    }
    printf("FDTEST heartbeat PASS beats=%d\n", beat);
    printf("FDTEST DONE pass=1 fail=0\n");
    fflush(stdout);
    return 0;
}
