import multiprocessing as mp
from rdf_graph_gen.rdf_graph_generator import *
from datetime import datetime

class MultiprocessGenerator:
    def __init__(self, shape_file, output_file, graph_number, batch_size):
        self.shape_file = shape_file
        self.output_file = output_file
        self.graph_number = graph_number
        self.batch_size = batch_size
        
        self.shape = Graph()
        self.shape.parse(self.shape_file)
        self.dictionary = generate_dictionary_from_shapes_graph(self.shape)

    def worker(self, gueue, batchID, batch_size):
    
        graph = generate_rdf_graphs_from_dictionary(self.shape, self.dictionary, batch_size, batchID)
        graph = graph.serialize(format = 'ttl')
        gueue.put(graph)
        return graph

    def listener(self, gueue):

        with open(self.output_file, 'w') as file:
            while True:
                res = gueue.get()
                if res == 'finished generating':
                    break
                file.write(res)
                file.flush()

    def generate(self):

        manager = mp.Manager()
        queue = manager.Queue()    
        pool = mp.Pool(mp.cpu_count() + 2)

        watcher = pool.apply_async(self.listener, (queue,))
        
        start = datetime.now()
        
        jobs = []
        batch = 1
        while self.graph_number > 0:
            
            batch_size = min(self.graph_number, self.batch_size)
            
            job = pool.apply_async(self.worker, (queue, f'B{batch}', batch_size))
            jobs.append(job)
            
            self.graph_number -= self.batch_size
            batch += 1
            
        for job in jobs: 
            job.get()
    
        queue.put('finished generating')
        pool.close()
        pool.join()
        
        time_delta = datetime.now() - start
        
        print(f'Generator ran on {mp.cpu_count()} CPUs, finished in {time_delta}.')
