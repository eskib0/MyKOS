// Termina al instante (simula un backend que se cae nada más arrancar). Uso: node exit-now.cjs [código]
console.error("exit-now: terminando a propósito");
process.exit(Number(process.argv[2] ?? 1));
