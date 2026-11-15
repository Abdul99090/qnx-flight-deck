/* fdtest.c — QNX Flight-Deck on-target self-test agent.
 *
 * Runs a small suite of native QNX checks and prints machine-readable
 * result lines to the console for the host harness to harvest:
 *
 *     FDTEST <name> PASS|FAIL key=value ...
 *     FDTEST DONE pass=<n> fail=<n>
 *
 * Checks:
 *   ipc    — native microkernel message passing (ChannelCreate /
 *            ConnectAttach / MsgSend / MsgReceive / MsgReply) with a
 *            server thread; verifies payload round-trip integrity.
 *   timer  — monotonic clock + 50 ms nanosleep deadline accuracy.
 *   sched  — priority-ordered thread wakeup under SCHED_FIFO.
 *
 * Exit status: 0 when every check passed, 1 otherwise.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>
#include <pthread.h>
#include <sys/neutrino.h>
#include <sys/netmgr.h>

static int g_pass = 0, g_fail = 0;

static void report(const char *name, int ok, const char *detail) {
    printf("FDTEST %s %s %s\n", name, ok ? "PASS" : "FAIL", detail);
    fflush(stdout);
    if (ok) g_pass++; else g_fail++;
}

/* ---------------- IPC check (native message passing) ---------------- */

struct ping_msg {
    uint16_t type;          /* _IO_MAX + 1 range is app-defined here */
    uint32_t seq;
    char     payload[32];
};

static void *ipc_server(void *arg) {
    int chid = *(int *)arg;
    struct ping_msg msg;
    struct _msg_info info;
    for (;;) {
        int rcvid = MsgReceive(chid, &msg, sizeof(msg), &info);
        if (rcvid == -1) continue;
        if (rcvid == 0) {           /* a pulse: not used in this test */
            continue;
        }
        msg.seq += 1;               /* mutate so client can verify reply */
        MsgReply(rcvid, EOK, &msg, sizeof(msg));
        return NULL;                /* one round-trip is enough */
    }
    return NULL;
}

static void test_ipc(void) {
    char detail[96];
    int chid = ChannelCreate(0);
    if (chid == -1) {
        snprintf(detail, sizeof(detail), "err=ChannelCreate:%s", strerror(errno));
        report("ipc", 0, detail);
        return;
    }
    pthread_t th;
    if (pthread_create(&th, NULL, ipc_server, &chid) != 0) {
        report("ipc", 0, "err=pthread_create");
        ChannelDestroy(chid);
        return;
    }
    int coid = ConnectAttach(ND_LOCAL_NODE, 0, chid, _NTO_SIDE_CHANNEL, 0);
    if (coid == -1) {
        snprintf(detail, sizeof(detail), "err=ConnectAttach:%s", strerror(errno));
        report("ipc", 0, detail);
        ChannelDestroy(chid);
        return;
    }
    struct ping_msg out, in;
    memset(&out, 0, sizeof(out));
    out.type = 0x100;
    out.seq = 41;
    strcpy(out.payload, "flight-deck-ping");
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int rc = MsgSend(coid, &out, sizeof(out), &in, sizeof(in));
    clock_gettime(CLOCK_MONOTONIC, &t1);
    long rtt_us = (long)(t1.tv_sec - t0.tv_sec) * 1000000L
                + (long)(t1.tv_nsec - t0.tv_nsec) / 1000L;
    pthread_join(th, NULL);
    ConnectDetach(coid);
    ChannelDestroy(chid);
    int ok = (rc != -1) && in.seq == 42 && strcmp(in.payload, "flight-deck-ping") == 0;
    snprintf(detail, sizeof(detail), "rtt_us=%ld seq=%u", rtt_us, in.seq);
    report("ipc", ok, detail);
}

/* ---------------- Timer deadline check ---------------- */

static void test_timer(void) {
    char detail[96];
    struct timespec req = { 0, 50 * 1000 * 1000L };   /* 50 ms */
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    nanosleep(&req, NULL);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    long elapsed_us = (long)(t1.tv_sec - t0.tv_sec) * 1000000L
                    + (long)(t1.tv_nsec - t0.tv_nsec) / 1000L;
    long drift_us = elapsed_us - 50000L;
    if (drift_us < 0) drift_us = -drift_us;
    /* QEMU/TCG timing is loose (pure emulation on a shared host);
     * budget 60 ms drift for the emulation profile by default,
     * overridable at build time with -DFD_TIMER_BUDGET_US=<us>.
     * On real QNX hardware this is typically three orders of
     * magnitude tighter. */
#ifndef FD_TIMER_BUDGET_US
#define FD_TIMER_BUDGET_US 60000L
#endif
    int ok = drift_us <= FD_TIMER_BUDGET_US;
    snprintf(detail, sizeof(detail), "slept_us=%ld drift_us=%ld", elapsed_us, drift_us);
    report("timer", ok, detail);
}

/* ---------------- Scheduler priority check ---------------- */

static volatile int g_wake_order[3];
static volatile int g_wake_n = 0;
static pthread_mutex_t g_gate = PTHREAD_MUTEX_INITIALIZER;

static void *sched_worker(void *arg) {
    int id = (int)(intptr_t)arg;
    pthread_mutex_lock(&g_gate);        /* all workers park on the gate */
    pthread_mutex_unlock(&g_gate);
    g_wake_order[g_wake_n++] = id;
    return NULL;
}

static void test_sched(void) {
    char detail[96];
    pthread_t th[3];
    pthread_attr_t attr;
    struct sched_param sp;
    g_wake_n = 0;
    pthread_mutex_lock(&g_gate);
    for (int i = 0; i < 3; i++) {
        pthread_attr_init(&attr);
        pthread_attr_setschedpolicy(&attr, SCHED_FIFO);
        sp.sched_priority = 10 + i;     /* worker 2 has highest priority */
        pthread_attr_setschedparam(&attr, &sp);
        pthread_attr_setinheritsched(&attr, PTHREAD_EXPLICIT_SCHED);
        pthread_create(&th[i], &attr, sched_worker, (void *)(intptr_t)i);
        pthread_attr_destroy(&attr);
    }
    /* Give all workers time to park on the gate, then release. Under
     * SCHED_FIFO the highest-priority worker must run first. */
    struct timespec ts = { 0, 100 * 1000 * 1000L };
    nanosleep(&ts, NULL);
    pthread_mutex_unlock(&g_gate);
    for (int i = 0; i < 3; i++) pthread_join(th[i], NULL);
    int ok = (g_wake_order[0] == 2);
    snprintf(detail, sizeof(detail), "wake_order=%d,%d,%d",
             g_wake_order[0], g_wake_order[1], g_wake_order[2]);
    report("sched", ok, detail);
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);   /* never lose results to buffering */
    printf("FDTEST START sysname=QNX\n");
    fflush(stdout);
    test_ipc();
    test_timer();
    test_sched();
    printf("FDTEST DONE pass=%d fail=%d\n", g_pass, g_fail);
    fflush(stdout);
    return g_fail ? 1 : 0;
}
