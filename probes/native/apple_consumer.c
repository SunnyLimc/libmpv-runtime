#include <stdio.h>
#include <mpv/client.h>

int main(void) {
    unsigned long version = mpv_client_api_version();
    printf("%lu.%lu\n", version >> 16, version & 0xffffUL);
    return version == 0 ? 1 : 0;
}
