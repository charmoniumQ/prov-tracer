#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>

#define NUM_THREADS 5

typedef struct {
    long thread_id;
    int* shared_counter;
    pthread_mutex_t* mutex;
} thread_args_t;

void* increment_counter(void* args) {
    thread_args_t* thread_args = (thread_args_t*) args;
    long tid = thread_args->thread_id;
    int* counter = thread_args->shared_counter;
    pthread_mutex_t* mutex = thread_args->mutex;

    printf("Thread #%ld: starting.\n", tid);

    pthread_mutex_lock(mutex);
    printf("Thread #%ld: acquired the lock.\n", tid);

    (*counter)++;
    printf("Thread #%ld: incremented counter to %d.\n", tid, *counter);

    pthread_mutex_unlock(mutex);
    printf("Thread #%ld: released the lock.\n", tid);

    pthread_exit(NULL);
}

int main() {
    pthread_t threads[NUM_THREADS];
    thread_args_t thread_args[NUM_THREADS];
    pthread_mutex_t mutex;
    int shared_counter = 0;
    int rc;
    long t;

    pthread_mutex_init(&mutex, NULL);

    for (t = 0; t < NUM_THREADS; t++) {
        printf("In main: creating thread %ld\n", t);
        thread_args[t].thread_id = t;
        thread_args[t].shared_counter = &shared_counter;
        thread_args[t].mutex = &mutex;

        rc = pthread_create(&threads[t], NULL, increment_counter, (void*)&thread_args[t]);
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

    pthread_mutex_destroy(&mutex);

    printf("Main: program exiting. Final counter value: %d\n", shared_counter);
    pthread_exit(NULL);
}
