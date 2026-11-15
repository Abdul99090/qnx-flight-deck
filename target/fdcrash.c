/* fdcrash.c — crash-harvest demo target.
 * Prints one passing check, then deliberately segfaults so the
 * harness can demonstrate crash detection + reporting. */
#include <stdio.h>
#include <string.h>

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    printf("FDTEST START sysname=QNX\n");
    printf("FDTEST pre-crash PASS note=about-to-fault\n");
    volatile char *p = (volatile char *)0x1;
    *p = 42;                    /* SIGSEGV */
    printf("FDTEST unreachable PASS\n");
    return 0;
}
