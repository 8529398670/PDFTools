// An Emscripten file system that keeps files on the origin's private disk
// (OPFS), for what qpdf writes in the split worker. Emscripten's own in-memory
// file system grows a file by an eighth at a time, copying it each time, so a
// 50 MB section left some 400 MB of garbage behind it; written through here, a
// section never sits in memory at all. Together with WORKERFS for the source,
// qpdf's memory stays flat (about 16 MB of wasm heap) however big the book.
//
// OPFS sync access handles are opened asynchronously, and qpdf's writes are
// synchronous, so a file has to be prepared (opened) before qpdf touches it:
// prepare(path) before each qpdf call that writes. Nothing else can create a
// file here. Removing a file (FS.unlink) deletes it from the disk too;
// release(path) closes one that is kept, leaving it for the page to read.
//
// Usage (in a dedicated worker):
//   const out = new OpfsFS( module.FS , folderHandle );
//   FS.mkdir( "/out" ); FS.mount( out , {} , "/out" );
//   await out.prepare( "/out/00001.pdf" ); ... qpdf writes it ...
//   await out.release( "/out/00001.pdf" );
class OpfsFS {
  constructor( FS , folder ) {
    this.FS = FS;
    this.folder = folder;
    this.root = null;
    this.removals = [];
    const self = this;
    const FILE = 33279;
    const DIR = 16895;
    this.FILE_MODE = FILE;
    this.DIR_MODE = DIR;
    const errno = ( code ) => new FS.ErrnoError( code );

    this.node_ops = {
      getattr( node ) {
        const size = node.sync ? node.sync.getSize() : node.mode === FILE ? node.size || 0 : 4096;
        return { dev: 1 , ino: node.id , mode: node.mode , nlink: 1 , uid: 0 , gid: 0 , rdev: 0 , size: size ,
          atime: new Date( node.atime ) , mtime: new Date( node.mtime ) , ctime: new Date( node.ctime ) ,
          blksize: 4096 , blocks: Math.ceil( size / 4096 ) };
      },
      setattr( node , attr ) {
        for ( const key of [ "mode" , "atime" , "mtime" , "ctime" ] ) if ( attr[ key ] != null ) node[ key ] = attr[ key ];
        if ( attr.size != null && node.sync ) node.sync.truncate( attr.size );
      },
      lookup() { throw errno( 44 ); },
      // Only prepared files exist: anything else qpdf tries to create is refused.
      mknod() { throw errno( 63 ); },
      rename() { throw errno( 63 ); },
      unlink( parent , name ) {
        const node = parent.contents[ name ];
        if ( node && node.sync ) node.sync.close();
        delete parent.contents[ name ];
        self.removals.push( self.folder.removeEntry( name ).catch( () => {} ) );
      },
      rmdir() { throw errno( 63 ); },
      readdir( node ) { return [ "." , ".." , ...Object.keys( node.contents ) ]; },
      symlink() { throw errno( 63 ); },
    };

    this.stream_ops = {
      read( stream , buffer , offset , length , position ) {
        return stream.node.sync.read( buffer.subarray( offset , offset + length ) , { at: position } );
      },
      write( stream , buffer , offset , length , position ) {
        return stream.node.sync.write( buffer.subarray( offset , offset + length ) , { at: position } );
      },
      llseek( stream , offset , whence ) {
        let position = offset;
        if ( whence === 1 ) position += stream.position;
        else if ( whence === 2 ) position += stream.node.sync.getSize();
        if ( position < 0 ) throw errno( 28 );
        return position;
      },
    };
  }

  // FS.mount calls this.
  mount() {
    this.root = this.createNode( null , "/" , this.DIR_MODE );
    return this.root;
  }

  createNode( parent , name , mode , sync ) {
    const node = this.FS.createNode( parent , name , mode );
    node.mode = mode;
    node.node_ops = this.node_ops;
    node.stream_ops = this.stream_ops;
    node.atime = node.mtime = node.ctime = Date.now();
    node.contents = mode === this.DIR_MODE ? {} : null;
    node.sync = sync || null;
    if ( parent ) parent.contents[ name ] = node;
    return node;
  }

  name( path ) {
    return path.slice( path.lastIndexOf( "/" ) + 1 );
  }

  // Opens (creating, emptied) the file at path so qpdf can write and read it.
  async prepare( path ) {
    await this.settle();
    const name = this.name( path );
    const handle = await this.folder.getFileHandle( name , { create: true } );
    const sync = await handle.createSyncAccessHandle();
    sync.truncate( 0 );
    const old = this.root.contents[ name ];
    if ( old ) {
      if ( old.sync ) old.sync.close();
      this.FS.destroyNode( old );
      delete this.root.contents[ name ];
    }
    this.createNode( this.root , name , this.FILE_MODE , sync );
  }

  // Closes a finished file and answers its name in the folder, where the page
  // reads it from. The node stays, empty-handed, until the folder is unmounted.
  async release( path ) {
    const name = this.name( path );
    const node = this.root.contents[ name ];
    if ( node && node.sync ) {
      node.sync.flush();
      node.size = node.sync.getSize();
      node.sync.close();
      node.sync = null;
    }
    return name;
  }

  // Waits for the deletions unlink started.
  async settle() {
    const pending = this.removals;
    this.removals = [];
    await Promise.all( pending );
  }

  // Closes whatever is still open, before unmounting.
  async close() {
    Object.values( this.root ? this.root.contents : {} ).forEach( ( node ) => {
      if ( node.sync ) node.sync.close();
      node.sync = null;
    } );
    await this.settle();
  }
}
