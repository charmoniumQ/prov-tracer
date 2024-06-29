#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <unistd.h> 
#include <time.h>   

#define NUM_THREADS 5
#define NUM_COUNTERS 3

typedef struct {
    long thread_id;
    int* shared_counters;
    pthread_mutex_t* mutexes;
    pthread_barrier_t* barrier;
} thread_args_t;

void* increment_counters(void* args) {
    thread_args_t* thread_args = (thread_args_t*) args;
    long tid = thread_args->thread_id;
    int* counters = thread_args->shared_counters;
    pthread_mutex_t* mutexes = thread_args->mutexes;
    pthread_barrier_t* barrier = thread_args->barrier;

    printf("Thread #%ld: starting.\n", tid);

    int sleep_time = rand() % 3 + 1;
    printf("Thread #%ld: sleeping for %d seconds.\n", tid, sleep_time);
    sleep(sleep_time);

    for (int i = 0; i < NUM_COUNTERS; i++) {
        pthread_mutex_lock(&mutexes[i]);
        printf("Thread #%ld: acquired lock for counter %d.\n", tid, i);
        counters[i]++;
        printf("Thread #%ld: incremented counter %d to %d.\n", tid, i, counters[i]);
        pthread_mutex_unlock(&mutexes[i]);
        printf("Thread #%ld: released lock for counter %d.\n", tid, i);
    }

char filename[20];
sprintf(filename, "%ld.txt", tid);  // Filename without directory prefix
FILE* file = fopen(filename, "w");
if (file != NULL) {
    fprintf(file, "Thread #%ld was here\n", tid);
    fclose(file);
} else {
    printf("Thread #%ld: failed to write file.\n", tid);
}


    printf("Thread #%ld: waiting at barrier.\n", tid);
    pthread_barrier_wait(barrier);
    printf("Thread #%ld: passed the barrier.\n", tid);

    pthread_exit(NULL);
}

int main() {
    pthread_t threads[NUM_THREADS];
    thread_args_t thread_args[NUM_THREADS];
    pthread_mutex_t mutexes[NUM_COUNTERS];
    pthread_barrier_t barrier;
    int shared_counters[NUM_COUNTERS] = {0};
    int rc;
    long t;

    srand(time(NULL));

    for (int i = 0; i < NUM_COUNTERS; i++) {
        pthread_mutex_init(&mutexes[i], NULL);
    }

    pthread_barrier_init(&barrier, NULL, NUM_THREADS);

    for (t = 0; t < NUM_THREADS; t++) {
        printf("In main: creating thread %ld\n", t);
        thread_args[t].thread_id = t;
        thread_args[t].shared_counters = shared_counters;
        thread_args[t].mutexes = mutexes;
        thread_args[t].barrier = &barrier;

        rc = pthread_create(&threads[t], NULL, increment_counters, (void*)&thread_args[t]);
        if (rc) {
            printf("ERROR; return code from pthread_create() is %d\n", rc);
            exit(-1);
        }
    }

    for (t = 0; t < NUM_THREADS; t++) {
        rc = pthread_join(threads[t], NULL);
        if (rc) {
            printf("ERROR; return code from pthread_join() is %d\n", rc);
            exit(-1);
        }
    }

    for (int i = 0; i < NUM_COUNTERS; i++) {
        pthread_mutex_destroy(&mutexes[i]);
    }

    pthread_barrier_destroy(&barrier);

    printf("Main: checking files written by threads:\n");
    for (t = 0; t < NUM_THREADS; t++) {
        char filename[20];
        sprintf(filename, "/tmp/%ld.txt", t);
        FILE* file = fopen(filename, "r");
        if (file != NULL) {
            char buffer[50];
            fgets(buffer, 50, file);
            printf("File /tmp/%ld.txt content: %s", t, buffer);
            fclose(file);
        } else {
            printf("File /tmp/%ld.txt not found.\n", t);
        }
    }

    printf("Main: program exiting. Final counter values:\n");
    for (int i = 0; i < NUM_COUNTERS; i++) {
        printf("Counter %d: %d\n", i, shared_counters[i]);
    }

    pthread_exit(NULL);
}

